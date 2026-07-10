"""Layer 3 重要性综合评分器。

根据 LTM_WRITE_STRATEGY.md 的设计，实现 5 维评分模型，
作为 write_decision() 的 Layer 3 判断依据。

评分维度:
    - identity_score:  0.30 — 是否涉及用户身份/偏好
    - state_score:     0.20 — 是否涉及状态/配置变更
    - task_score:      0.20 — 任务重要性（来自 Evaluator）
    - cold_start_score:0.15 — LTM 冷启动保护
    - quality_score:   0.15 — LLM 输出质量（reward_score）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── 身份模式 ─────────────────────────────────────────────────
_IDENTITY_PATTERNS = re.compile(
    r"我是|我叫|我住在|我在|我偏好|我喜欢|我讨厌|"
    r"我的邮箱|我的电话|我的地址|我的账户|我的角色|"
    r"i am|my name is|i live in|i prefer|i like|i hate",
    re.IGNORECASE,
)

# ── 状态变更模式 ─────────────────────────────────────────────
_STATE_PATTERNS = re.compile(
    r"余额|余额为|金额|总额|修改|更新|设置|配置|"
    r"balance|amount|update|set|config|change|modify",
    re.IGNORECASE,
)

_STATE_NUMBER_PATTERN = re.compile(
    r"[\d.,]+\s*(元|个|人|次|万|亿|dollars|users|times|items)",
)

# ── 高价值事实模式 ───────────────────────────────────────────
_FACT_PATTERNS = re.compile(
    r"记住|记录|保存|设置为|不要忘记|务必|切记|规则|规定|规则是|"
    r"remember|save|set to|don't forget|always|never|rule|policy",
    re.IGNORECASE,
)


@dataclass
class ImportanceScore:
    """Layer 3 综合评分结果。"""

    overall: float
    identity: float
    state: float
    task: float
    cold_start: float
    quality: float
    breakdown: dict[str, float] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.overall >= 0.5


class ImportanceScorer:
    """Layer 3 综合重要性评分器。

    权重（初始实验值，后续通过 A/B 测试和 reward 反馈调优）:
        identity_weight:  0.30
        state_weight:     0.20
        task_weight:      0.20
        cold_start_weight: 0.15
        quality_weight:   0.15

    阈值: overall >= 0.5 则判定为值得存储。
    """

    def __init__(
        self,
        identity_weight: float = 0.30,
        state_weight: float = 0.20,
        task_weight: float = 0.20,
        cold_start_weight: float = 0.15,
        quality_weight: float = 0.15,
        cold_start_threshold: int = 50,
        pass_threshold: float = 0.5,
    ):
        self.W_identity = identity_weight
        self.W_state = state_weight
        self.W_task = task_weight
        self.W_cold_start = cold_start_weight
        self.W_quality = quality_weight
        self.cold_start_threshold = cold_start_threshold
        self.pass_threshold = pass_threshold

    def score(
        self,
        content: str,
        *,
        task_intent: str = "",
        task_importance: float = 0.5,
        reward_score: float = 0.5,
        ltm_count: int = 0,
        entities: Optional[list[str]] = None,
    ) -> ImportanceScore:
        """对候选内容进行综合评分。

        Args:
            content: 待评分内容文本。
            task_intent: 当前任务意图（如 "agent", "qa", "coding"）。
            task_importance: 任务重要性（0~1，来自 Evaluator）。
            reward_score: LLM 输出质量分（0~1，来自 Evaluator）。
            ltm_count: 当前 LTM 总条目数（用于冷启动判断）。
            entities: 提取出的实体列表。

        Returns:
            ImportanceScore，overall >= 0.5 表示建议存储。
        """
        id_score = self._identity_score(content)
        st_score = self._state_score(content, task_intent)
        tk_score = self._task_score(task_importance)
        cs_score = self._cold_start_score(ltm_count)
        qu_score = self._quality_score(reward_score)

        overall = (
            id_score * self.W_identity
            + st_score * self.W_state
            + tk_score * self.W_task
            + cs_score * self.W_cold_start
            + qu_score * self.W_quality
        )

        return ImportanceScore(
            overall=round(min(overall, 1.0), 4),
            identity=id_score,
            state=st_score,
            task=tk_score,
            cold_start=cs_score,
            quality=qu_score,
            breakdown={
                "identity": id_score,
                "state": st_score,
                "task": tk_score,
                "cold_start": cs_score,
                "quality": qu_score,
            },
        )

    # ── 各维度评分方法 ────────────────────────────────────────

    @staticmethod
    def _identity_score(content: str) -> float:
        """检测是否涉及用户身份或偏好。

        包含"我是/我住在/我偏好"等身份声明模式则高分。
        """
        ct = content.lower()
        hits = len(_IDENTITY_PATTERNS.findall(ct))
        if hits >= 2:
            return 1.0
        if hits == 1:
            return 0.8
        # 检查是否有第一人称 + 强声明动词
        if re.search(r"(我|my|i)\s.{0,10}(是|住|在|喜欢|偏好|prefer|like)", ct):
            return 0.6
        return 0.1

    @staticmethod
    def _state_score(content: str, task_intent: str) -> float:
        """检测是否涉及状态或配置变更。

        Intent 为 agent/coding/workflow 且含数字/金额 → 高分。
        """
        ct = content.lower()

        # 命中状态模式
        state_hits = len(_STATE_PATTERNS.findall(ct))

        # 检查是否有数字值（金额、数量等）
        has_numbers = bool(_STATE_NUMBER_PATTERN.search(ct))

        # 是否包含事实关键字
        fact_hits = len(_FACT_PATTERNS.findall(ct))

        if fact_hits >= 2:
            return 0.9
        if state_hits >= 2 and has_numbers:
            return 0.9
        if state_hits >= 1 and has_numbers:
            return 0.8
        # 状态类意图 + 包含数字
        if task_intent in ("agent", "coding", "workflow") and has_numbers:
            return 0.7
        if state_hits >= 1:
            return 0.5
        # 规则关键词命中
        if fact_hits == 1:
            return 0.7
        return 0.2

    @staticmethod
    def _task_score(task_importance: float) -> float:
        """基于任务重要性评分。

        由 Evaluator 提供的 task_importance 直接映射。
        """
        return min(max(task_importance, 0.0), 1.0)

    def _cold_start_score(self, ltm_count: int) -> float:
        """冷启动保护评分。

        当 LTM 条目数 < cold_start_threshold 时，加权放宽写入门槛。
        ltm_count 越小 → 分值越高 → 更容易通过决策。
        """
        if ltm_count >= self.cold_start_threshold:
            return 0.0
        if ltm_count <= 0:
            return 1.0
        # 线性衰减: ltm_count=0→1.0, ltm_count=threshold→0.0
        return max(0.0, 1.0 - ltm_count / self.cold_start_threshold)

    @staticmethod
    def _quality_score(reward_score: float) -> float:
        """基于 LLM 输出质量评分。

        由 Evaluator 提供的 reward_score 直接映射。
        """
        return min(max(reward_score, 0.0), 1.0)
