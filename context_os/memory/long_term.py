"""长期记忆（Long-Term Memory）。

跨 Session、跨项目的持久记忆。基于 SQLite 存储，支持:
    - 向量相似度检索（需 sqlite3 插件）
    - BM25 关键词检索
    - 时间衰减排序
    - 访问频率加权
    - Ebbinghaus 遗忘曲线自动清理

存储内容:
    - 用户长期偏好（语言、风格、规范）
    - 项目上下文和代码库知识
    - 跨 Session 的用户行为模式
    - 重要的决策记录和理由
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from context_os.core.logger import get_logger
from context_os.memory.store import SQLiteStore
from context_os.core.models import MemoryItem, MemoryType

logger = get_logger(__name__)

# BM25 参数
_BM25_K1 = 1.5
_BM25_B = 0.75
# 混合检索权重（有 embedding 时）— Phase 4 统一评分公式
_W_SEM = 0.40
_W_KW = 0.25
_W_REL = 0.15
_W_TIME = 0.10
_W_ACCESS = 0.10
# 混合检索权重（无 embedding 时）
_W_KW_ONLY = 0.55
_W_REL_ONLY = 0.20
_W_TIME_ONLY = 0.15
_W_ACCESS_ONLY = 0.10
# 时间衰减系数（每日）
_TIME_DECAY_LAMBDA = 0.01
# 同意图提升倍数
_INTENT_BOOST = 1.2
# 时间回溯检索的时间衰减系数（回溯时更弱，让旧记忆也有机会被检索）
_TIME_DECAY_LAMBDA_EXPAND = 0.001
# 时间回溯关键词
_TEMPORAL_KEYWORDS = re.compile(
    r"(?:我叫过|之前叫|原来叫|以前叫|以前设置|曾经|原来|之前|上次|"
    r"过去|历史|old\s+name|previous|before|used\s+to|history)",
    re.IGNORECASE,
)


class LongTermMemory:
    """长期记忆 — 跨 Session 持久知识库。

    Args:
        store: SQLite 存储层实例。
        user_id: 默认用户 ID。
        embedding_provider: 语义嵌入引擎（可选）。提供后可自动做向量检索。
    """

    def __init__(
        self,
        store: SQLiteStore,
        user_id: str = "anonymous",
        embedding_provider: Optional[Any] = None,
    ):
        self.store = store
        self.user_id = user_id
        self._embedding_provider = embedding_provider
        logger.info("LongTermMemory initialized (user=%s)", user_id)

    @staticmethod
    def detect_temporal_query(text: str) -> bool:
        """检测是否为时间回溯查询（Phase 4.5）。

        检测用户是否在询问历史信息：
            "我叫过什么"
            "之前叫什么"
            "以前设置过什么"

        Args:
            text: 用户输入文本。

        Returns:
            True 如果是时间回溯查询。
        """
        return bool(_TEMPORAL_KEYWORDS.search(text))

    async def save(
        self,
        content: str,
        memory_type: str = "long_term",
        metadata: Optional[dict] = None,
        embedding: Optional[list[float]] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """存储一条长期记忆。

        Args:
            content: 记忆内容。
            memory_type: 子类型（long_term|semantic|user_profile|project_context）。
            metadata: 元数据，如 {"category": "user_preference", "key": "language"}。
            embedding: 向量嵌入，未提供时将自动用 embedding_provider 生成。
            user_id: 用户 ID，默认使用构造函数中设置的。

        Returns:
            记忆 ID。
        """
        # 自动生成 embedding
        if embedding is None and self._embedding_provider is not None:
            try:
                embedding = await self._embedding_provider.embed(content)
            except Exception as e:
                logger.warning("Auto-embedding failed, saving without it: %s", e)

        mem_id = uuid.uuid4().hex
        await self.store.save_memory(
            id=mem_id,
            type=memory_type,
            content=content,
            user_id=user_id or self.user_id,
            embedding=embedding,
            metadata=metadata,
        )
        logger.info(
            "LTM saved: id=%s, type=%s, content_len=%d, has_embedding=%s",
            mem_id, memory_type, len(content), embedding is not None,
        )
        return mem_id

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        memory_type: Optional[str] = None,
        embedding: Optional[list[float]] = None,
        intent: Optional[str] = None,
        expand_history: bool = False,
    ) -> list[MemoryItem]:
        """检索长期记忆（增强型混合检索）。

        多因子融合公式:
            score = α · semantic + β · bm25 + γ · relevance + δ · time_decay + ε · access_freq

        额外:
            - 同 intent 记忆获 1.2x 提升
            - 有 embedding 时启用语义检索，无时退化为 BM25+时效+相关性
            - expand_history=True 时，时间衰减削弱 10x，候选量扩大 3x

        Args:
            query: 检索查询文本。
            top_k: 返回数量上限。
            memory_type: 筛选特定子类型。
            embedding: 直接传入向量进行相似度检索。
            intent: 当前任务意图，用于匹配 metadata.intent（如 "qa"、"planning"）。
            expand_history: 是否启用时间回溯检索（Phase 4.5）。

        Returns:
            MemoryItem 列表，按综合得分降序排列。
        """
        # ── 1. 为查询生成语义向量（如果有 embedding_provider） ──
        if self._embedding_provider is not None and embedding is None:
            try:
                embedding = await self._embedding_provider.embed(query)
            except Exception as e:
                logger.warning("Query embedding failed: %s", e)
                embedding = None

        # ── 2. 查候选记忆 ──
        # expand_history 时扩大候选池 3x
        candidate_limit = 1500 if expand_history else 500
        all_results = await self.store.query_memories(
            type=memory_type or "long_term",
            user_id=self.user_id,
            query_text=query if embedding is None else None,
            top_k=candidate_limit,
        )

        if not all_results:
            return []

        # ── 3. BM25 批量打分准备 ──
        query_lower = query.lower() if query else ""
        all_content = [(r.get("content") or "") for r in all_results]
        now = datetime.now(timezone.utc)

        scored: list[tuple[float, dict, float, float]] = []

        for i, r in enumerate(all_results):
            # 语义分
            sem_score = 0.0
            if embedding is not None:
                stored_emb = r.get("embedding")
                if stored_emb and len(stored_emb) == len(embedding):
                    sem_score = self._cosine_similarity(embedding, stored_emb)

            # BM25 关键词分
            kw_score = 0.0
            if query_lower:
                kw_score = self._bm25_score(query_lower, all_content, i)

            # 时效衰减（expand_history 时使用更弱的衰减系数）
            days_old = 0
            ts_str = r.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    days_old = (now - ts).days
                except Exception:
                    pass
            decay_lambda = _TIME_DECAY_LAMBDA_EXPAND if expand_history else _TIME_DECAY_LAMBDA
            time_decay = math.exp(-decay_lambda * max(0, days_old))

            # 相关性和访问频率
            relevance = min(r.get("relevance_score") or 0.0, 1.0)
            access_norm = min((r.get("access_count") or 0) / 10.0, 1.0)

            # 多因子融合
            if embedding is not None:
                final = (
                    _W_SEM * sem_score
                    + _W_KW * kw_score
                    + _W_REL * relevance
                    + _W_TIME * time_decay
                    + _W_ACCESS * access_norm
                )
            else:
                final = (
                    _W_KW_ONLY * kw_score
                    + _W_REL_ONLY * relevance
                    + _W_TIME_ONLY * time_decay
                    + _W_ACCESS_ONLY * access_norm
                )

            # Intent 匹配提升
            if intent and r.get("metadata", {}).get("intent") == intent:
                final *= _INTENT_BOOST

            scored.append((final, r, sem_score, kw_score))

        # ── 4. 排序返回 ──
        scored.sort(key=lambda x: x[0], reverse=True)

        # 自适应 top_k：候选数多时自动扩量，确保覆盖充分
        effective_top_k = top_k
        if len(scored) > 50:
            effective_top_k = min(top_k * 4, len(scored), 50)
            logger.debug(
                "Adaptive top_k: %d -> %d (candidates=%d)",
                top_k, effective_top_k, len(scored),
            )

        top = []
        for _, r, _, _ in scored[:effective_top_k]:
            try:
                top.append(MemoryItem(**r))
            except Exception as e:
                logger.warning(
                    "MemoryItem deserialization failed (id=%s): %s",
                    r.get("id", "?"), e,
                )
                continue

        logger.info(
            "LTM hybrid retrieved: query='%s...', top_k=%d (eff=%d), total_candidates=%d, "
            "top_sem=%.3f, top_kw=%.3f, intent=%s",
            query[:50], top_k, len(top), len(all_results),
            scored[0][2] if scored else 0,
            scored[0][3] if scored else 0,
            intent or "none",
        )
        return top

    async def retrieve_by_category(self, category: str, top_k: int = 10) -> list[MemoryItem]:
        """按类别检索长期记忆。

        Args:
            category: 类别名（如 "user_preference", "project_context", "decision"）。
            top_k: 返回上限。

        Returns:
            MemoryItem 列表。
        """
        # 使用关键词匹配 metadata.category
        results = await self.store.query_memories(
            type="long_term",
            user_id=self.user_id,
            query_text=category,
            top_k=top_k,
        )
        items: list[MemoryItem] = []
        for r in results:
            if r.get("metadata", {}).get("category") != category:
                continue
            try:
                items.append(MemoryItem(**r))
            except Exception as e:
                logger.warning(
                    "MemoryItem deserialization failed (id=%s): %s",
                    r.get("id", "?"), e,
                )
        logger.debug("LTM by category '%s': %d results", category, len(items))
        return items

    async def update_relevance(self, memory_id: str, delta: float = 0.1) -> None:
        """更新某条记忆的相关性得分。

        通常在 LLM 实际使用了该记忆时调用，增加其得分。

        Args:
            memory_id: 记忆 ID。
            delta: 得分增量。
        """
        mem = await self.store.get_memory(memory_id)
        if mem:
            new_score = min((mem.get("relevance_score") or 0.0) + delta, 1.0)
            await self.store.execute(
                "UPDATE memories SET relevance_score = ? WHERE id = ?",
                [new_score, memory_id],
            )
            logger.debug("LTM relevance updated: id=%s, new_score=%.2f", memory_id, new_score)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算余弦相似度。"""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = nA = nB = 0.0
        for va, vb in zip(a, b):
            dot += va * vb
            nA += va * va
            nB += vb * vb
        denom = (nA ** 0.5) * (nB ** 0.5)
        return dot / denom if denom != 0 else 0.0

    @staticmethod
    def _bm25_score(query: str, documents: list[str], idx: int) -> float:
        """BM25 关键词评分（语料感知，含 TF-IDF + 文档长度归一化）。"""
        if not query or idx < 0 or not documents or idx >= len(documents):
            return 0.0

        q_tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", query.lower())
        doc_tokens = [
            re.findall(r"[a-z0-9\u4e00-\u9fff]+", d.lower()) for d in documents
        ]

        if not q_tokens or not doc_tokens[idx]:
            return 0.0

        doc_len = len(doc_tokens[idx])
        avg_doc_len = sum(len(t) for t in doc_tokens) / len(doc_tokens) if doc_tokens else 1.0
        n_docs = len(documents)

        score = 0.0
        for token in q_tokens:
            tf = doc_tokens[idx].count(token)
            if tf == 0:
                continue
            df = sum(1 for d in doc_tokens if token in d)
            idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
            score += idf * (tf * (_BM25_K1 + 1)) / (
                tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_len / avg_doc_len)
            )

        return score

    async def consolidate(self) -> int:
        """记忆整合：去重 + 语义合并。

        执行流程:
            1. 精确内容去重
            2. 基于 cosine 相似度的语义合并（有 embedding 时）
            3. 标记过时条目

        Returns:
            整合后移除的条目数。
        """
        results = await self.store.query_memories(
            type="long_term",
            user_id=self.user_id,
            top_k=1000,
        )

        if not results:
            return 0

        # 1. 精确去重：内容相同的保留一条
        seen_contents: dict[str, str] = {}
        to_delete: list[str] = []

        for r in results:
            content = r.get("content", "").strip()
            if not content:
                continue
            if content in seen_contents:
                to_delete.append(r["id"])
            else:
                seen_contents[content] = r["id"]

        # 2. 语义去重：内容相似度高的保留较详细的版本（有 embedding 时）
        if self._embedding_provider is not None and len(seen_contents) > 1:
            content_list = list(seen_contents.keys())
            id_list = [seen_contents[c] for c in content_list]
            try:
                embeddings = await self._embedding_provider.embed_batch(content_list)
                for i in range(len(content_list)):
                    for j in range(i + 1, len(content_list)):
                        if id_list[j] in to_delete:
                            continue
                        sim = self._cosine_similarity(embeddings[i], embeddings[j])
                        if sim > 0.85:
                            # 保留较长的版本，删除较短的
                            if len(content_list[i]) >= len(content_list[j]):
                                to_delete.append(id_list[j])
                            else:
                                to_delete.append(id_list[i])
            except Exception as e:
                logger.warning("Semantic consolidation failed: %s", e)

        for mem_id in to_delete:
            await self.store.delete_memory(mem_id)

        if to_delete:
            logger.info("LTM consolidated: removed %d entries", len(to_delete))
        else:
            logger.debug("LTM consolidate: no duplicates found")

        return len(to_delete)

    # ── Summary（Phase 5: 非结构化摘要存储）───────────────

    async def save_summary(
        self,
        content: str,
        category: str = "summary",
        confidence: float = 0.7,
        source: str = "write_decision",
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """保存一条无 entity_key 的非结构化 Summary。

        不同于 save_fact: 不按 entity_key 覆盖，不做版本链。
        去重基于 embedding 相似度:
            sim > 0.9 → 内容对比 → 有新增信息则合并加速旧条目的 decay
            sim < 0.9 → 新增

        Args:
            content: 摘要内容。
            category: 类别（默认 "summary"）。
            confidence: 置信度。
            source: 来源。
            user_id: 用户 ID。

        Returns:
            记忆 ID（跳过去重时返回 None）。
        """
        uid = user_id or self.user_id
        import json
        import uuid as _uuid
        from datetime import datetime, timezone

        # 1. embedding 去重
        if self._embedding_provider is not None:
            try:
                query_emb = await self._embedding_provider.embed(content)
                existing = await self.store.query_memories(
                    type="long_term", user_id=uid, top_k=50,
                )

                # 找到与 metadata.ltm_subtype="summary" 的最相似条目
                max_sim = 0.0
                best_match = None
                for r in existing:
                    meta = r.get("metadata", {}) or {}
                    if meta.get("ltm_subtype") != "summary":
                        continue
                    stored_emb = r.get("embedding")
                    if not stored_emb:
                        continue
                    if isinstance(stored_emb, str):
                        try:
                            stored_emb = json.loads(stored_emb)
                        except (json.JSONDecodeError, TypeError):
                            continue
                    if len(stored_emb) != len(query_emb):
                        continue
                    sim = self._cosine_similarity(query_emb, stored_emb)
                    if sim > max_sim:
                        max_sim = sim
                        best_match = r

                if max_sim > 0.9 and best_match is not None:
                    # 内容对比
                    existing_content = best_match.get("content", "")
                    if self._has_new_info(content, existing_content):
                        # 合并：新内容存储，旧条目加速 decay
                        await self.store.execute(
                            "UPDATE memories SET relevance_score = MAX(0, relevance_score - 0.3) "
                            "WHERE id = ?",
                            [best_match["id"]],
                        )
                        logger.debug(
                            "Summary merge: new info detected, old entry %s decayed",
                            best_match["id"],
                        )
                    else:
                        logger.debug("Summary dedup: sim=%.3f, truly duplicate", max_sim)
                        return None

            except Exception as e:
                logger.warning("Summary dedup failed, storing: %s", e)

        # 2. 存储
        mem_id = _uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()

        # 自动生成 embedding
        embedding = None
        if self._embedding_provider is not None:
            try:
                embedding = await self._embedding_provider.embed(content)
            except Exception:
                pass

        await self.store.save_memory(
            id=mem_id,
            type="long_term",
            content=content,
            user_id=uid,
            embedding=embedding,
            metadata={
                "category": category,
                "ltm_subtype": "summary",
                "confidence": confidence,
                "source": source,
                "created_at": now,
            },
        )
        logger.info(
            "LTM Summary saved: id=%s, category=%s, len=%d",
            mem_id, category, len(content),
        )
        return mem_id

    @staticmethod
    def _has_new_info(new_text: str, old_text: str) -> bool:
        """简单的文本差异检测：新文本是否有旧文本没有的句子。"""
        new_sentences = set(s.strip() for s in re.split(r"[。；.!?;]", new_text) if s.strip())
        old_sentences = set(s.strip() for s in re.split(r"[。；.!?;]", old_text) if s.strip())
        new_only = new_sentences - old_sentences
        return len(new_only) > 0

    # ── Fact（原 FactMemory，已合并到 metadata） ──────────────

    async def save_fact(
        self,
        fact_id: str,
        content: str,
        category: str,
        confidence: float = 1.0,
        source: str = "",
        user_id: Optional[str] = None,
    ) -> str:
        """保存/更新一条版本化事实（原 FactMemory.set）。

        content 存入 memories.content，其余字段（category/confidence/version/
        source/history）均放入 metadata JSON。版本号自动递增，旧值存入 history
        数组，便于后续时间回溯检索。

        Args:
            fact_id: 事实 ID（如 entity_key，用于去重和更新）。
            content: 事实内容/当前值。
            category: 类别（如 "user_profile", "project_config"）。
            confidence: 置信度 (0-1)。
            source: 来源说明。
            user_id: 用户 ID。

        Returns:
            记忆 ID。
        """
        uid = user_id or self.user_id
        import json
        import uuid
        from datetime import datetime, timezone

        # 查找已有记录
        existing = await self.store.query_memories(
            type="long_term",
            user_id=uid,
            top_k=200,
        )
        existing_record = None
        for r in existing:
            meta = r.get("metadata", {})
            if isinstance(meta, dict) and meta.get("fact_id") == fact_id:
                existing_record = r
                break

        now = datetime.now(timezone.utc).isoformat()

        if existing_record:
            existing_meta = existing_record.get("metadata", {})
            if not isinstance(existing_meta, dict):
                existing_meta = {}
            history = existing_meta.get("history", [])
            history.append({
                "value": existing_record.get("content", ""),
                "version": existing_meta.get("version", 1),
                "updated_at": now,
            })
            new_version = existing_meta.get("version", 1) + 1
            new_meta = {
                "category": category,
                "fact_id": fact_id,
                "confidence": confidence,
                "version": new_version,
                "source": source,
                "history": history,
            }
            # 更新：用原 ID 覆盖
            mem_id = existing_record["id"]
            await self.store.save_memory(
                id=mem_id,
                type="long_term",
                content=content,
                user_id=uid,
                metadata=new_meta,
            )
            logger.debug(
                "Fact updated: fact_id=%s, v%d -> v%d", fact_id,
                existing_meta.get("version", 1), new_version,
            )
            return mem_id

        # 新事实
        mem_id = uuid.uuid4().hex
        new_meta = {
            "category": category,
            "fact_id": fact_id,
            "confidence": confidence,
            "version": 1,
            "source": source,
            "history": [],
        }
        await self.store.save_memory(
            id=mem_id,
            type="long_term",
            content=content,
            user_id=uid,
            metadata=new_meta,
        )
        logger.info("Fact created: fact_id=%s, category=%s", fact_id, category)
        return mem_id

    async def get_fact(self, fact_id: str, user_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """按 fact_id 获取事实（含版本和 history）。

        Args:
            fact_id: 事实 ID。
            user_id: 用户 ID。

        Returns:
            事实记录 dict（含 content, metadata.version, metadata.history 等），或 None。
        """
        uid = user_id or self.user_id
        results = await self.store.query_memories(
            type="long_term",
            user_id=uid,
            top_k=200,
        )
        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, dict) and meta.get("fact_id") == fact_id:
                return r
        return None

    async def query_facts(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        user_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """按类别查询事实（原 FactMemory.query）。

        Args:
            category: 类别名（可选）。
            limit: 返回上限。
            user_id: 用户 ID。

        Returns:
            事实记录 dict 列表。
        """
        uid = user_id or self.user_id
        results = await self.store.query_memories(
            type="long_term",
            user_id=uid,
            top_k=500,  # 先多取再过滤
        )
        facts = []
        for r in results:
            meta = r.get("metadata", {})
            if not isinstance(meta, dict):
                continue
            if meta.get("fact_id") and meta.get("category"):
                if category and meta.get("category") != category:
                    continue
                facts.append(r)
                if len(facts) >= limit:
                    break
        # 按时间倒序
        facts.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return facts

    async def query_summaries(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        user_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """按类别查询摘要（Phase 8 补齐，对应 MEMORY_SYSTEM_DESIGN §5.2）。

        过滤条件：type='long_term' 且 metadata.ltm_subtype='summary'。
        Summary 没有 entity_key，不可 diff，不可覆盖，纯语义检索。

        Args:
            category: 类别过滤（可选，匹配 metadata.category）。
            limit: 返回上限。
            user_id: 用户 ID。

        Returns:
            摘要记录 dict 列表，按时间倒序。
        """
        uid = user_id or self.user_id
        results = await self.store.query_memories(
            type="long_term",
            user_id=uid,
            top_k=500,
        )
        summaries: list[dict[str, Any]] = []
        for r in results:
            meta = r.get("metadata", {})
            if isinstance(meta, str):
                import json
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(meta, dict):
                continue
            # 过滤：ltm_subtype == 'summary'
            if meta.get("ltm_subtype") != "summary":
                continue
            if category and meta.get("category") != category:
                continue
            summaries.append(r)
            if len(summaries) >= limit:
                break
        # 按时间倒序
        summaries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return summaries

    # ── 衰减 ────────────────────────────────────────────────────

    async def decay_relevance(self, half_life_days: float = 7.0) -> int:
        """衰减所有 LTM 记忆的 relevance_score（时间衰减）。

        Summary 使用 3 天半衰期，Fact 使用 7 天半衰期。

        Args:
            half_life_days: 默认半衰期（天）。Summary 会使用更快的 3 天。

        Returns:
            更新的记忆数。
        """
        import json
        from datetime import datetime, timezone

        if not self.store.is_connected:
            return 0

        results = await self.store.query_memories(
            type="long_term", user_id=self.user_id, top_k=5000,
        )
        if not results:
            return 0

        now = datetime.now(timezone.utc)
        fact_lambda = math.log(2) / half_life_days
        summary_lambda = math.log(2) / 3.0  # Summary 固定 3 天半衰期
        updated = 0

        for r in results:
            ts_str = r.get("timestamp")
            if not ts_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                days_old = max(0, (now - ts).days)
            except Exception:
                continue

            meta = r.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}

            is_summary = isinstance(meta, dict) and meta.get("ltm_subtype") == "summary"
            decay_lambda = summary_lambda if is_summary else fact_lambda

            decay_factor = math.exp(-decay_lambda * days_old)
            current_score = r.get("relevance_score") or 0.0
            new_score = round(current_score * decay_factor, 4)
            new_score = max(new_score, 0.01)

            if abs(new_score - current_score) > 0.001:
                await self.store.execute(
                    "UPDATE memories SET relevance_score = ? WHERE id = ?",
                    [new_score, r["id"]],
                )
                updated += 1

        if updated > 0:
            logger.info(
                "LTM decay_relevance: %d memories updated (fact_hl=%.1fd, summary_hl=3.0d)",
                updated, half_life_days,
            )
        return updated

    # ── 清理 ────────────────────────────────────────────────────

    async def forget(self, threshold_days: int = 90, min_access_count: int = 2) -> int:
        """基于遗忘曲线自动清理低价值记忆。

        清理条件:
            - 超过 threshold_days 未访问
            - 访问次数低于 min_access_count
            - 相关性得分低于 0.3

        Args:
            threshold_days: 阈值天数。
            min_access_count: 最低访问次数。

        Returns:
            清理的记忆数。
        """
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)

        if not self.store.is_connected:
            return 0

        cursor = await self.store.execute(
            "DELETE FROM memories "
            "WHERE type = 'long_term' "
            "AND user_id = ? "
            "AND timestamp < ? "
            "AND access_count < ? "
            "AND relevance_score < 0.3",
            [self.user_id, cutoff.isoformat(), min_access_count],
        )
        count = cursor.rowcount

        if count > 0:
            logger.info("LTM forget: removed %d low-value memories", count)
        return count
