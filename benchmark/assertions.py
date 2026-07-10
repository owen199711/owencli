"""模块级断言 — 验证 Context-OS 每个环节的正确性。

每个断言函数返回 (passed: bool, details: dict) 二元组。
"""

from __future__ import annotations

from typing import Any, Optional

from context_os.core.models import IntentType, MemoryType, TaskSpec, UnifiedContext


# ═══════════════════════════════════════════════════════════════════
# Intent Layer 断言
# ═══════════════════════════════════════════════════════════════════

def assert_intent(
    task: TaskSpec,
    expected_intent: Optional[IntentType] = None,
    expected_goal: Optional[str] = None,
    min_confidence: float = 0.0,
) -> tuple[bool, dict]:
    """验证意图分类结果。

    Args:
        task: Pipeline Step 1 输出的 TaskSpec。
        expected_intent: 期望的 IntentType（None 表示不验证）。
        expected_goal: 期望的 Goal（None 表示不验证）。
        min_confidence: 最低可信度阈值。

    Returns:
        (passed, details) 二元组。
    """
    issues = []
    if expected_intent and task.intent != expected_intent:
        issues.append(
            f"意图不匹配: 期望={expected_intent.value}, 实际={task.intent.value}"
        )
    if expected_goal and task.goal.value != expected_goal:
        issues.append(
            f"目标不匹配: 期望={expected_goal}, 实际={task.goal.value}"
        )
    if task.confidence < min_confidence:
        issues.append(f"置信度过低: {task.confidence:.2f} < {min_confidence:.2f}")

    return len(issues) == 0, {
        "intent": task.intent.value,
        "goal": task.goal.value,
        "confidence": task.confidence,
        "entities": [e.model_dump() for e in task.entities],
        "issues": issues,
    }


# ═══════════════════════════════════════════════════════════════════
# Collection Layer 断言
# ═══════════════════════════════════════════════════════════════════

def assert_collection(
    unified: UnifiedContext,
    expected_counts: Optional[dict[str, int]] = None,
) -> tuple[bool, dict]:
    """验证 Collection Layer 收集到的上下文。

    Args:
        unified: Pipeline Step 2 输出的 UnifiedContext。
        expected_counts: 期望的各类型数量，如 {"conversation_turns": 5, "memory_count": 3}。

    Returns:
        (passed, details) 二元组。
    """
    counts = {
        "identity_present": unified.identity is not None,
        "conversation_turns": len(unified.conversation.history)
        if unified.conversation and unified.conversation.history
        else 0,
        "environment_present": unified.environment is not None,
        "memory_count": len(unified.memory),
        "knowledge_count": len(unified.knowledge),
        "tool_count": len(unified.tools),
    }

    # 按 MemoryType 统计
    memory_type_counts: dict[str, int] = {}
    for m in unified.memory:
        t = m.type.value if isinstance(m.type, MemoryType) else str(m.type)
        memory_type_counts[t] = memory_type_counts.get(t, 0) + 1
    counts["memory_by_type"] = memory_type_counts

    issues = []
    if expected_counts:
        for key, expected in expected_counts.items():
            actual = counts.get(key, 0)
            if actual != expected:
                issues.append(f"{key}: 期望={expected}, 实际={actual}")

    return len(issues) == 0, {**counts, "issues": issues}


# ═══════════════════════════════════════════════════════════════════
# Builder 断言
# ═══════════════════════════════════════════════════════════════════

def assert_builder(
    before_memory_count: int,
    after_memory_count: int,
    dedup_expected: Optional[int] = None,
) -> tuple[bool, dict]:
    """验证 Builder 的去重/合并效果。

    Args:
        before_memory_count: Builder 处理前的记忆条目数。
        after_memory_count: Builder 处理后的记忆条目数。
        dedup_expected: 期望去重数量。

    Returns:
        (passed, details) 二元组。
    """
    dedup_count = before_memory_count - after_memory_count
    issues = []
    if dedup_expected is not None and dedup_count != dedup_expected:
        issues.append(
            f"去重数量不匹配: 期望={dedup_expected}, 实际={dedup_count}"
        )

    return len(issues) == 0, {
        "before_count": before_memory_count,
        "after_count": after_memory_count,
        "dedup_count": dedup_count,
        "issues": issues,
    }


# ═══════════════════════════════════════════════════════════════════
# Optimizer 断言
# ═══════════════════════════════════════════════════════════════════

def assert_optimizer(
    token_before: int,
    token_after: int,
    max_token_budget: Optional[int] = None,
    compression_ratio_min: Optional[float] = None,
) -> tuple[bool, dict]:
    """验证 Optimizer 的压缩和预算分配。

    Args:
        token_before: 优化前的 Token 数。
        token_after: 优化后的 Token 数。
        max_token_budget: 预算上限（None 表示不验证）。
        compression_ratio_min: 最低压缩率（如 0.3 表示至少压缩 30%）。

    Returns:
        (passed, details) 二元组。
    """
    issues = []
    if max_token_budget and token_after > max_token_budget:
        issues.append(
            f"超出预算: {token_after} > {max_token_budget}"
        )

    compression_ratio = 1.0 - (token_after / token_before) if token_before > 0 else 0
    if compression_ratio_min is not None and compression_ratio < compression_ratio_min:
        issues.append(
            f"压缩率不足: {compression_ratio:.1%} < {compression_ratio_min:.1%}"
        )

    return len(issues) == 0, {
        "token_before": token_before,
        "token_after": token_after,
        "compression_ratio": round(compression_ratio, 3),
        "token_reduced": token_before - token_after,
        "issues": issues,
    }


# ═══════════════════════════════════════════════════════════════════
# Memory 断言
# ═══════════════════════════════════════════════════════════════════

def assert_memory_counts(
    memory_counts: dict[str, int],
    expected: Optional[dict[str, int]] = None,
) -> tuple[bool, dict]:
    """验证各记忆类型的条目数。

    Args:
        memory_counts: 当前各类型记忆的数量，如 {"working": 2, "long_term": 5}。
        expected: 期望的各类型数量。

    Returns:
        (passed, details) 二元组。
    """
    issues = []
    if expected:
        for key, expected_count in expected.items():
            actual = memory_counts.get(key, 0)
            if actual < expected_count:
                issues.append(f"{key}: 期望>={expected_count}, 实际={actual}")

    return len(issues) == 0, {
        "memory_counts": memory_counts,
        "total": sum(memory_counts.values()),
        "issues": issues,
    }


# ═══════════════════════════════════════════════════════════════════
# Retriever 断言
# ═══════════════════════════════════════════════════════════════════

def assert_retriever_recall(
    retrieved_items: list[Any],
    relevant_items: set[str],
    top_k: int = 5,
) -> tuple[bool, dict]:
    """验证检索器的召回率。

    Args:
        retrieved_items: 检索到的条目列表。
        relevant_items: 相关条目 ID 或 content 集合。
        top_k: 检索数量上限。

    Returns:
        (passed, details) 二元组。
    """
    retrieved_set = set()
    for item in retrieved_items:
        content = item.content if hasattr(item, "content") else str(item)
        retrieved_set.add(content[:100])

    hits = sum(1 for rel in relevant_items if any(rel in r for r in retrieved_set))
    recall = hits / len(relevant_items) if relevant_items else 0.0
    precision = hits / len(retrieved_items) if retrieved_items else 0.0

    issues = []
    if recall < 0.5:
        issues.append(f"召回率过低: {recall:.1%}")

    return recall >= 0.5, {
        "hits": hits,
        "relevant_total": len(relevant_items),
        "recall": round(recall, 3),
        "precision": round(precision, 3),
        "issues": issues,
    }
