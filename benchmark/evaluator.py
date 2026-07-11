"""自动评分引擎 — 多层评测体系。

评测层级:
    Layer 1: 关键词匹配 (30%) — 快速筛查记忆召回
    Layer 2: LLM Judge (40%) — LLM 对答案质量打分
    Layer 3: 结构化比对 (30%) — JSON 字段级精确匹配
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class EvalScore:
    """单次评测结果。"""
    score: float  # 0.0 ~ 1.0
    details: dict = field(default_factory=dict)


@dataclass
class MultiLayerEvalResult:
    """多层评测结果。"""
    keyword_score: float = 0.0
    keyword_detail: dict = field(default_factory=dict)
    judge_score: float = 0.0
    judge_reason: str = ""
    structured_score: float = 0.0
    structured_detail: dict = field(default_factory=dict)
    final_score: float = 0.0
    passed: bool = False


class EvaluationEngine:
    """自动评分引擎。

    支持三种评测模式:
        1. keyword_eval — 关键词召回率
        2. llm_judge — LLM 评分 + 理由
        3. structured_compare — JSON 结构化比对
    """

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client

    # ═══════════════════════════════════════════════════════════════
    # Layer 1: 关键词匹配
    # ═══════════════════════════════════════════════════════════════

    def keyword_eval(
        self,
        response: str,
        expected_keywords: list[str],
        question: str = "",
    ) -> EvalScore:
        """关键词召回率评测。

        过滤掉问题文本自带的关键词，只对需要从记忆召回的词评分。

        Args:
            response: LLM 回复。
            expected_keywords: 期望的关键词列表。
            question: 当前问题文本（用于过滤问题自带的词）。

        Returns:
            EvalScore(score=0.0~1.0, details=...)
        """
        if not expected_keywords:
            return EvalScore(1.0, {"note": "无关键词需要匹配", "memory_kw": []})

        # 过滤问题自带的词
        question_lower = question.lower() if question else ""
        memory_kw = [
            kw for kw in expected_keywords
            if kw.lower() not in question_lower
        ]
        if not memory_kw:
            return EvalScore(1.0, {
                "note": "所有关键词均出自问题文本",
                "filtered": len(expected_keywords) - len(memory_kw),
            })

        resp_lower = response.lower()
        hits = sum(1 for kw in memory_kw if kw.lower() in resp_lower)
        score = hits / len(memory_kw)

        return EvalScore(score, {
            "hits": hits,
            "total_memory_kw": len(memory_kw),
            "filtered_question_kw": len(expected_keywords) - len(memory_kw),
            "keywords": memory_kw,
        })

    # ═══════════════════════════════════════════════════════════════
    # Layer 2: LLM Judge
    # ═══════════════════════════════════════════════════════════════

    async def llm_judge(
        self,
        question: str,
        expected: str = "",
        response: str = "",
        expected_json: Optional[dict[str, Any]] = None,
    ) -> EvalScore:
        """LLM Judge — 调用 LLM 对回答质量进行评分。

        优先使用 expected_json 构造可读的期望答案；
        如果 expected_json 为空才使用 expected（自然语言 ground_truth）。

        Args:
            question: 问题。
            expected: 自然语言期望答案（备用，将被 expected_json 优先覆盖）。
            response: 实际回答。
            expected_json: 结构化期望数据（优先使用，自动构造可读评分标准）。

        Returns:
            EvalScore(score=0.0~1.0, details={"reason": ..., "raw_score": 0-10})
        """
        if not self.llm_client:
            return EvalScore(0.5, {"note": "无 LLM Judge 客户端"})

        expected_block = self._build_expected_answer(expected, expected_json)

        prompt = (
            "你是一位严谨的评测员。请根据期望答案标准，对 AI 的回答进行评分（0-10 分）。\n\n"
            f"【问题】\n{question}\n\n"
            f"{expected_block}\n\n"
            f"【AI 回答】\n{response[:2000]}\n\n"
            "评分标准：\n"
            "- 10: 完全正确，信息完整，逻辑清晰\n"
            "- 7-9: 大部分正确，少量遗漏或不够精确\n"
            "- 4-6: 部分正确，有较多遗漏或错误\n"
            "- 1-3: 基本错误或无关\n"
            "- 0: 完全错误或拒绝回答\n\n"
            "请返回 JSON 格式：\n"
            '{"score": <0-10整数>, "reason": "<评分理由，指出具体问题>"}'
        )

        try:
            result = await self.llm_client.complete(
                prompt=prompt,
                response_format="json",
                max_tokens=300,
                temperature=0.2,
            )
            if isinstance(result, str):
                parsed = json.loads(result)
            else:
                parsed = result

            raw_score = int(parsed.get("score", 5))
            reason = parsed.get("reason", "")
            score = max(0.0, min(1.0, raw_score / 10.0))

            return EvalScore(score, {
                "raw_score": raw_score,
                "reason": reason,
            })
        except Exception as e:
            return EvalScore(0.5, {"error": str(e), "note": "LLM Judge 调用失败"})

    @staticmethod
    def _build_expected_answer(
        ground_truth: str = "",
        expected_json: Optional[dict[str, Any]] = None,
    ) -> str:
        """从 expected_json 或 ground_truth 构建可读的期望答案标准。

        优先使用 expected_json 构造结构化期望标准；
        其次使用 ground_truth 作为自然语言期望答案。

        Args:
            ground_truth: 自然语言期望答案（备用）。
            expected_json: 结构化期望数据（优先）。

        Returns:
            格式化的期望答案文本块。
        """
        if expected_json:
            items = "\n".join(
                f"  - {k}: {v}"
                for k, v in expected_json.items()
            )
            return f"【期望答案标准】（请逐项检查 AI 回答是否包含以下关键信息）\n{items}"

        if ground_truth:
            return f"【期望答案】\n{ground_truth}"

        return "【期望答案】（未提供期望答案，请根据问题语义自行判断回答质量）"

    # ═══════════════════════════════════════════════════════════════
    # Layer 3: 结构化比对
    # ═══════════════════════════════════════════════════════════════

    def structured_compare(
        self,
        response: str,
        expected_json: dict[str, Any],
    ) -> EvalScore:
        """结构化 JSON 比对。

        Args:
            response: LLM 回复文本。
            expected_json: 期望的结构化数据。

        Returns:
            EvalScore(score=0.0~1.0, details={matched/total/errors/...})
        """
        matched = 0
        total = 0
        errors = []

        for key, expected_value in expected_json.items():
            total += 1
            expected_str = str(expected_value).lower()
            if expected_str in response.lower():
                matched += 1
            else:
                errors.append(f"缺少字段 '{key}': 期望值 '{expected_value}' 未在回复中找到")

        score = matched / total if total > 0 else 1.0
        return EvalScore(score, {
            "matched": matched,
            "total": total,
            "errors": errors,
            "accuracy": round(score, 3),
        })

    # ═══════════════════════════════════════════════════════════════
    # 综合评测
    # ═══════════════════════════════════════════════════════════════

    async def evaluate(
        self,
        response: str,
        question: str,
        expected_keywords: list[str],
        ground_truth: str = "",
        expected_json: Optional[dict[str, Any]] = None,
    ) -> MultiLayerEvalResult:
        """三层综合评测。

        Args:
            response: LLM 回复。
            question: 当前问题。
            expected_keywords: 期望关键词列表。
            ground_truth: 标准答案文本（用于 LLM Judge）。
            expected_json: 期望的结构化数据。

        Returns:
            MultiLayerEvalResult。
        """
        result = MultiLayerEvalResult()

        # Layer 1: 关键词
        kw = self.keyword_eval(response, expected_keywords, question)
        result.keyword_score = kw.score
        result.keyword_detail = kw.details

        # Layer 2: LLM Judge
        # 只要有 expected_json 或 ground_truth 即可启用 Judge
        if self.llm_client and (ground_truth or expected_json):
            judge = await self.llm_judge(
                question=question,
                expected=ground_truth,
                response=response,
                expected_json=expected_json,
            )
            result.judge_score = judge.score
            result.judge_reason = judge.details.get("reason", judge.details.get("error", ""))
        else:
            result.judge_score = kw.score  # 降级使用关键词分

        # Layer 3: 结构化比对
        if expected_json:
            struct = self.structured_compare(response, expected_json)
            result.structured_score = struct.score
            result.structured_detail = struct.details
        else:
            result.structured_score = kw.score  # 降级

        # 综合评分 (30% kw + 40% judge + 30% struct)
        result.final_score = (
            0.30 * result.keyword_score
            + 0.40 * result.judge_score
            + 0.30 * result.structured_score
        )
        result.passed = result.final_score >= 0.6

        return result


def extract_json_from_response(response: str) -> Optional[dict]:
    """从 LLM 回复中提取 JSON 块。

    查找回复中的 ```json ... ``` 或 {...} 块。
    """
    # 先尝试找 ```json 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试找 {...}
    m = re.search(r"\{.*\}", response, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None
