"""输出质量评估器。

评估 LLM 回复的质量、幻觉风险、工具准确性等维度。
"""

from __future__ import annotations

from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.core.models import EvalMetrics, PackagedContext

logger = get_logger(__name__)


class QualityEvaluator:
    """质量评估器。

    Args:
        llm_client: 可选的大模型客户端，用于质量评分。
    """

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client
        logger.info("QualityEvaluator initialized (llm=%s)", "available" if llm_client else "None")

    async def evaluate(
        self,
        packed: PackagedContext,
        llm_response: str,
        latency_ms: float,
        token_count: int,
    ) -> EvalMetrics:
        """评估一次 LLM 调用的质量。

        Args:
            packed: 打包后的 Context。
            llm_response: LLM 的回复文本。
            latency_ms: 延迟（毫秒）。
            token_count: 消耗的 Token 数。

        Returns:
            EvalMetrics。
        """
        logger.info("Evaluating response quality...")

        success = self._check_success(llm_response)
        cost = self._estimate_cost(token_count)

        quality = 0.0
        if self.llm_client and success:
            quality = await self._rate_quality(packed.raw_prompt, llm_response)
        else:
            quality = 0.8 if success else 0.1

        reward = quality * (0.8 if success else 0.2)

        metrics = EvalMetrics(
            answer_quality=round(quality, 3),
            latency_ms=round(latency_ms, 1),
            cost_usd=round(cost, 6),
            success=success,
            reward_score=round(reward, 3),
        )

        logger.info(
            "Evaluation: quality=%.3f, latency=%.0fms, cost=$%.5f, success=%s, reward=%.3f",
            metrics.answer_quality, metrics.latency_ms, metrics.cost_usd,
            metrics.success, metrics.reward_score,
        )
        return metrics

    @staticmethod
    def _check_success(response: str) -> bool:
        """检查回复是否成功（无错误信息）。"""
        error_signals = ["error", "unable to", "cannot", "failed", "apologies"]
        first_200 = response[:200].lower()
        return not any(sig in first_200 for sig in error_signals)

    @staticmethod
    def _estimate_cost(tokens: int) -> float:
        """按 Claude Sonnet 价格估算: $3/M input。"""
        return tokens * 3.0 / 1_000_000

    async def _rate_quality(self, prompt: str, response: str) -> float:
        """调用 LLM 对回复质量评分 0-1。"""
        try:
            eval_prompt = (
                "Rate the following AI response on a scale of 0.0 to 1.0.\n"
                "Consider: accuracy, completeness, clarity, helpfulness.\n"
                "Return ONLY a number between 0 and 1.\n\n"
                f"Response: {response[:2000]}"
            )
            result = await self.llm_client.complete(eval_prompt, max_tokens=50, temperature=0.3)
            return max(0.0, min(1.0, float(str(result).strip())))
        except Exception as e:
            logger.warning("Quality rating failed: %s", e)
            return 0.5
