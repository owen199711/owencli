"""Knowledge 子系统 — 知识提取与队列管理。

与 Memory 独立：不同生命周期、不同存储、不同检索接口。
"""

from context_os.knowledge.queue import KnowledgeQueue
from context_os.knowledge.updater import KnowledgeUpdater

__all__ = ["KnowledgeQueue", "KnowledgeUpdater"]
