"""增强模块断言 — Collection/Builder/Optimizer/Feedback/Reflection 验证。

每个函数返回 (score: float, details: dict) 二元组，score 为 0.0 ~ 1.0。
"""

from __future__ import annotations

from typing import Any, Optional

from context_os.core.models import UnifiedContext, MemoryType


# ═══════════════════════════════════════════════════════════════════
# Collection Layer 验证
# ═══════════════════════════════════════════════════════════════════

def verify_collection(
    unified: UnifiedContext,
    expected_counts: Optional[dict[str, int]] = None,
) -> tuple[float, dict]:
    """验证 Collection Layer 是否收集到正确的各类型 Context。

    检测项目:
        - Conversation: 对话历史轮次
        - Identity: 用户身份
        - Environment: 环境信息
        - Memory: 各类型记忆数量
        - Tools: 工具上下文

    Returns:
        (score 0~1, details)
    """
    scores = {}
    issues = []

    # Conversation
    conv_turns = len(unified.conversation.history) if unified.conversation and unified.conversation.history else 0
    scores["conversation"] = min(1.0, conv_turns / max(expected_counts.get("conversation", 1), 1)) if expected_counts and "conversation" in expected_counts else (1.0 if conv_turns > 0 else 0.0)

    # Identity
    scores["identity"] = 1.0 if unified.identity is not None else 0.0
    if not unified.identity:
        issues.append("Identity 未收集")

    # Environment
    scores["environment"] = 1.0 if unified.environment is not None else 0.0

    # Memory by type
    memory_by_type: dict[str, int] = {}
    for m in unified.memory:
        t = m.type.value if hasattr(m.type, "value") else str(m.type)
        memory_by_type[t] = memory_by_type.get(t, 0) + 1

    if expected_counts:
        for key, expected in expected_counts.items():
            if key.startswith("memory_"):
                mtype = key.replace("memory_", "")
                actual = memory_by_type.get(mtype, 0)
                scores[f"memory_{mtype}"] = min(1.0, actual / max(expected, 1))
                if actual < expected:
                    issues.append(f"记忆类型 {mtype}: 期望>={expected}, 实际={actual}")

    scores["memory_total"] = min(1.0, len(unified.memory) / max(expected_counts.get("memory_total", 1), 1)) if expected_counts and "memory_total" in expected_counts else (1.0 if len(unified.memory) > 0 else 0.0)

    # 综合得分
    score = sum(scores.values()) / max(len(scores), 1)

    return score, {
        "scores": scores,
        "collected": {
            "conversation_turns": conv_turns,
            "identity_present": unified.identity is not None,
            "environment_present": unified.environment is not None,
            "memory_count": len(unified.memory),
            "memory_by_type": memory_by_type,
        },
        "issues": issues,
    }


# ═══════════════════════════════════════════════════════════════════
# Builder 验证
# ═══════════════════════════════════════════════════════════════════

def verify_builder(
    raw_memory_count: int,
    final_memory_count: int,
    memory_types_before: Optional[dict[str, int]] = None,
    memory_types_after: Optional[dict[str, int]] = None,
) -> tuple[float, dict]:
    """验证 Builder 的去重/合并/排序效果。

    Args:
        raw_memory_count: 原始检索出的记忆条目数。
        final_memory_count: 经过 Builder 处理后的记忆条目数。
        memory_types_before: 处理前的类型分布。
        memory_types_after: 处理后的类型分布。

    Returns:
        (score 0~1, details)
    """
    issues = []
    details = {}

    # 去重验证
    dedup_count = raw_memory_count - final_memory_count
    if dedup_count < 0:
        issues.append(f"去重异常: final({final_memory_count}) > raw({raw_memory_count})")
        dedup_score = 0.5
    elif raw_memory_count > 0 and dedup_count == 0:
        # 没有去重不一定错（可能本身就没重复）
        dedup_score = 0.8
    else:
        dedup_score = 1.0

    details["raw_count"] = raw_memory_count
    details["final_count"] = final_memory_count
    details["dedup_count"] = dedup_count
    details["dedup_score"] = dedup_score

    # 类型完整性验证
    type_score = 1.0
    if memory_types_before and memory_types_after:
        for t, count in memory_types_before.items():
            after_count = memory_types_after.get(t, 0)
            if after_count < count * 0.5 and count > 2:
                issues.append(f"Builder 丢失了 {t} 类型记忆: {count}→{after_count}")
                type_score = 0.6

    details["types_before"] = memory_types_before
    details["types_after"] = memory_types_after
    details["type_score"] = type_score

    # 综合
    score = dedup_score * 0.6 + type_score * 0.4

    return score, {**details, "issues": issues, "final_score": round(score, 3)}


# ═══════════════════════════════════════════════════════════════════
# Optimizer 验证
# ═══════════════════════════════════════════════════════════════════

def verify_optimizer(
    token_before: int,
    token_after: int,
    budget_total: int = 128000,
    expect_compression: bool = True,
) -> tuple[float, dict]:
    """验证 Optimizer 的 Token 压缩和预算分配。

    检测:
        - 是否压缩 (token_after < token_before)
        - 是否在预算内 (token_after <= budget)
        - 压缩率是否合理

    Returns:
        (score 0~1, details)
    """
    issues = []
    details = {}

    # 压缩检测
    if token_before <= 0:
        return 0.5, {"note": "无 Token 数据", "issues": ["token_before <= 0"]}

    compression_ratio = 1.0 - (token_after / token_before)
    details["token_before"] = token_before
    details["token_after"] = token_after
    details["compression_ratio"] = round(compression_ratio, 3)

    # 评分维度
    compression_score = 1.0
    if expect_compression and compression_ratio <= 0:
        issues.append(f"未压缩: before={token_before}, after={token_after}")
        compression_score = 0.3
    elif compression_ratio > 0.5:
        compression_score = 1.0  # 压缩 > 50%
    elif compression_ratio > 0.2:
        compression_score = 0.8  # 压缩 20%~50%
    elif compression_ratio > 0:
        compression_score = 0.6  # 有压缩但很少

    budget_score = 1.0
    if token_after > budget_total:
        issues.append(f"超出预算: {token_after} > {budget_total}")
        budget_score = max(0.1, 1.0 - (token_after - budget_total) / budget_total)

    details["compression_score"] = compression_score
    details["budget_score"] = budget_score
    details["budget_total"] = budget_total

    score = compression_score * 0.6 + budget_score * 0.4

    return round(score, 3), {**details, "issues": issues, "final_score": round(score, 3)}


# ═══════════════════════════════════════════════════════════════════
# Feedback 验证
# ═══════════════════════════════════════════════════════════════════

def verify_feedback(
    answer_quality: float,
    reward_score: float,
    success: bool,
) -> tuple[float, dict]:
    """验证 Feedback Layer 的评估质量。

    检测:
        - 质量分合理性 (0~1)
        - Reward 与 Quality 的关联性
        - Success 标记

    Returns:
        (score 0~1, details)
    """
    issues = []
    details = {
        "answer_quality": answer_quality,
        "reward_score": reward_score,
        "success": success,
    }

    # Quality 在合理范围
    quality_ok = 0.0 <= answer_quality <= 1.0
    if not quality_ok:
        issues.append(f"Quality 异常: {answer_quality}")

    # Reward 与 Quality 正相关
    reward_ok = reward_score >= answer_quality * 0.5  # 至少 50% quality
    if not reward_ok:
        issues.append(f"Reward({reward_score}) 与 Quality({answer_quality}) 不匹配")

    # 评分
    score = 0.0
    if quality_ok:
        score += 0.4
    if reward_ok:
        score += 0.3
    if success:
        score += 0.3

    details["issues"] = issues
    details["final_score"] = round(score, 3)

    return round(score, 3), details


# ═══════════════════════════════════════════════════════════════════
# Reflection 验证
# ═══════════════════════════════════════════════════════════════════

def verify_reflection(
    response: str,
    expected_reflection: bool = True,
) -> tuple[float, dict]:
    """验证 LLM 回复中是否包含反思/分析。

    检测关键词:
        - 反思: "原因", "分析", "因为", "导致", "反思"
        - 改进: "下次", "建议", "优化", "改进"

    Returns:
        (score 0~1, details)
    """
    reflection_keywords = ["原因", "分析", "因为", "导致", "反思", "why", "because", "analyze"]
    improvement_keywords = ["下次", "建议", "优化", "改进", "improve", "suggest", "next time"]

    resp_lower = response.lower()

    reflection_hits = sum(1 for kw in reflection_keywords if kw in resp_lower)
    improvement_hits = sum(1 for kw in improvement_keywords if kw in resp_lower)

    has_reflection = reflection_hits >= 2  # 至少 2 个反思关键词
    has_improvement = improvement_hits >= 1

    if expected_reflection:
        score = (0.6 if has_reflection else 0.0) + (0.4 if has_improvement else 0.0)
    else:
        score = 1.0  # 不期望反思时默认满分

    issues = []
    if expected_reflection and not has_reflection:
        issues.append("未检测到反思内容（缺少分析类关键词）")

    return round(score, 3), {
        "has_reflection": has_reflection,
        "has_improvement": has_improvement,
        "reflection_hits": reflection_hits,
        "improvement_hits": improvement_hits,
        "issues": issues,
        "final_score": round(score, 3),
    }


# ═══════════════════════════════════════════════════════════════════
# Tool 调用验证
# ═══════════════════════════════════════════════════════════════════

def verify_tool_call(
    response: str,
    expected_tool_type: Optional[str] = None,
) -> tuple[float, dict]:
    """验证 LLM 回复中是否包含工具调用意图。

    检测: SQL/API/文件操作等工具调用信号。

    Returns:
        (score 0~1, details)
    """
    tool_signals = {
        "sql": ["SELECT", "INSERT", "UPDATE", "DELETE", "查询", "表", "数据库"],
        "api": ["API", "接口", "调用", "请求", "fetch", "http"],
        "file": ["文件", "读取", "写入", "open(", "with open"],
        "email": ["邮件", "发送", "email"],
    }

    resp_upper = response.upper()
    detected_tools = []

    for tool_type, signals in tool_signals.items():
        if any(s.upper() in resp_upper for s in signals):
            detected_tools.append(tool_type)

    has_tool = len(detected_tools) > 0
    type_match = not expected_tool_type or expected_tool_type in detected_tools

    score = (0.5 if has_tool else 0.0) + (0.5 if type_match else 0.0)

    issues = []
    if expected_tool_type and not type_match:
        issues.append(f"期望工具类型 '{expected_tool_type}'，检测到 {detected_tools}")

    return round(score, 3), {
        "detected_tools": detected_tools,
        "has_tool_call": has_tool,
        "type_match": type_match,
        "issues": issues,
        "final_score": round(score, 3),
    }


# ═══════════════════════════════════════════════════════════════════
# Intent Layer 验证
# ═══════════════════════════════════════════════════════════════════

# 从问题文本推导功能意图的关键词映射
TEXT_INTENT_KEYWORDS = {
    "STORE_FACT": ["记住", "记下", "记录", "保存", "存储", "初始", "设置", "初始化"],
    "UPDATE_FACT": ["改成", "改为", "修改", "更新", "更新为", "设置为", "改为", "回滚", "重置"],
    "QUERY_FACT": ["多少", "是什么", "哪些", "哪个", "分别", "查询", "告诉我", "请问", "现在"],
    "SUMMARY": ["总结", "归纳", "汇总", "概括", "综述", "综述一下", "综合"],
    "REFLECTION": ["为什么", "分析", "原因", "反思", "怎么导致", "为什么会出现", "失败原因"],
    "CALL_TOOL": ["调用", "执行", "查询数据库", "查", "发邮件", "调用API", "运行"],
}

def infer_functional_intent(text: str) -> str:
    """根据文本关键词推导功能意图。

    Returns:
        功能意图字符串（STORE_FACT / UPDATE_FACT / QUERY_FACT / SUMMARY / REFLECTION / CALL_TOOL）。
    """
    text_lower = text.lower()
    scores = {}
    for intent, keywords in TEXT_INTENT_KEYWORDS.items():
        scores[intent] = sum(1 for kw in keywords if kw in text_lower)

    if not any(scores.values()):
        return "UNKNOWN"

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "UNKNOWN"

# IntentType 枚举值到功能意图的映射
SYSTEM_TO_FUNCTIONAL_INTENT = {
    "data_analysis": "SUMMARY",
    "qa": "QUERY_FACT",
    "search": "QUERY_FACT",
    "agent": "CALL_TOOL",
    "workflow": "CALL_TOOL",
    "coding": "CALL_TOOL",
    "planning": "SUMMARY",
    "debugging": "REFLECTION",
}

def verify_intent(
    actual_system_intent: str,
    expected_intent: str,
    question: str = "",
) -> tuple[float, dict]:
    """验证意图分类是否正确。

    采用两层匹配:
        1. 系统 IntentType → 功能意图映射匹配
        2. 问题文本关键词推导匹配

    Returns:
        (score 0~1, details)
    """
    actual_lower = actual_system_intent.lower().strip()

    # Layer 1: 系统 IntentType 映射匹配
    mapped = SYSTEM_TO_FUNCTIONAL_INTENT.get(actual_lower, "")
    mapped_match = mapped == expected_intent

    # Layer 2: 问题文本推导匹配
    if question:
        inferred = infer_functional_intent(question)
        inferred_match = inferred == expected_intent
    else:
        inferred = ""
        inferred_match = False

    # 综合: 任一匹配即可
    match = mapped_match or inferred_match
    score = 1.0 if match else 0.0

    return score, {
        "expected": expected_intent,
        "actual_system": actual_system_intent,
        "mapped_functional": mapped,
        "inferred_from_text": inferred,
        "mapped_match": mapped_match,
        "inferred_match": inferred_match,
        "match": match,
    }
