"""Context-OS MCP Server — 为 Claude Code / Trae IDE 提供长期记忆能力。

通过 MCP 协议 (Model Context Protocol) 将 Context-OS 的记忆系统
暴露为工具调用，使 AI 编程助手具备跨会话的上下文管理能力。

使用方式:
    Claude Code 通过 stdio 自动拉起此服务器。

配置 (~/.claude/settings.json):
    {
      "mcpServers": {
        "context-os": {
          "command": "python",
          "args": ["path/to/claude_codex_mcp/server.py"],
          "env": {
            "DEEPSEEK_API_KEY": "your-key",
            "CONTEXT_OS_DB_PATH": "path/to/context_os.db"
          }
        }
      }
    }
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

# ── Context-OS 核心 ──────────────────────────────────────────
from context_os.entry import ContextOSPipeline
from context_os.llm.deepseek_client import DeepSeekClient

# ── 服务名 ──
SERVER_NAME = "context-os"
SERVER_VERSION = "0.1.0"

# ── FastMCP 实例 ──
mcp = FastMCP(
    SERVER_NAME,
    description="Context-OS 长期记忆系统 — 跨会话上下文管理",
    version=SERVER_VERSION,
)

# ── 全局 Pipeline 实例（懒初始化） ──
_pipeline: ContextOSPipeline | None = None


async def get_pipeline() -> ContextOSPipeline:
    """获取或创建全局 Pipeline 实例。"""
    global _pipeline
    if _pipeline is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        db_path = os.environ.get("CONTEXT_OS_DB_PATH", "./data/context_os.db")
        user_id = os.environ.get("CONTEXT_OS_USER_ID", "claude-codex")

        if not api_key:
            print("[context-os] WARNING: DEEPSEEK_API_KEY not set", file=sys.stderr)

        llm = DeepSeekClient(api_key=api_key)
        _pipeline = ContextOSPipeline(
            llm_client=llm,
            user_id=user_id,
            db_path=db_path,
        )
        await _pipeline._ensure_store()
        print(
            f"[context-os] Pipeline initialized: user={user_id}, db={db_path}",
            file=sys.stderr,
        )
    return _pipeline


async def close_pipeline() -> None:
    """关闭 Pipeline，释放资源。"""
    global _pipeline
    if _pipeline is not None:
        await _pipeline.close()
        _pipeline = None
        print("[context-os] Pipeline closed", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════
# 工具定义
# ═══════════════════════════════════════════════════════════════


@mcp.tool(
    name="remember",
    description="""存储一条信息到长期记忆。

Claude 在对话中发现以下内容时应当调用此工具：
1. 用户偏好（"我喜欢用 pnpm"）
2. 项目配置（"项目使用 Python 3.14"）
3. 重要事实（"数据库连接串在 .env 文件中"）
4. 任务状态（"正在开发登录功能"）
5. 用户决策（"我们决定用 PostgreSQL"）

信息会自动经过质量评估和重要性筛选，高质量内容将被持久化。""",
)
async def remember(
    content: str,
    category: str = "fact",
) -> str:
    """将信息存入长期记忆。

    Args:
        content: 要记住的内容文本。
        category: 记忆类别，可选值:
            - "preference": 用户偏好
            - "fact": 事实性信息
            - "state": 状态更新
            - "task": 任务记录
            - "decision": 决策记录

    Returns:
        存储结果描述。
    """
    pipeline = await get_pipeline()
    result = await pipeline.run(f"请记住以下{category}信息：{content}")
    return result["response"]


@mcp.tool(
    name="recall",
    description="""从长期记忆中检索与查询相关的信息。

在以下情况下调用：
1. 用户询问之前讨论过的内容
2. 需要参考项目的配置或约定
3. 需要了解用户的编程偏好
4. 跨会话需要恢复上下文

检索使用语义相似度 + BM25 关键词 + 时间衰减 + 访问频率
四因子混合排序，返回最相关的结果。""",
)
async def recall(
    query: str,
    top_k: int = 5,
) -> str:
    """从长期记忆中检索信息。

    Args:
        query: 检索关键词或自然语言问题。
        top_k: 返回的最大结果数量（1-20），默认 5。

    Returns:
        检索到的记忆内容。
    """
    pipeline = await get_pipeline()
    result = await pipeline.run(f"请帮我查询以下信息：{query}")
    return result["response"]


@mcp.tool(
    name="forget",
    description="""从记忆中删除指定内容。

仅在用户明确要求忘记某条信息时调用。
需要先通过 recall 获取要删除的记忆 ID。""",
)
async def forget(
    memory_id: str,
) -> str:
    """从记忆中删除指定条目。

    Args:
        memory_id: 要删除的记忆条目 ID。
            （通过 recall 工具获取）

    Returns:
        删除结果。
    """
    pipeline = await get_pipeline()
    success = await pipeline.store.delete_memory(memory_id)
    if success:
        return f"✅ 已删除记忆 {memory_id}"
    return f"❌ 未找到记忆 {memory_id}"


@mcp.tool(
    name="summarize_session",
    description="""总结当前会话的关键信息并存入长期记忆。

在以下情况下调用：
1. 对话即将结束
2. 用户要求总结
3. 上下文窗口即将用尽前
4. 完成一个重要任务后

会自动提取关键决策、配置变更、用户偏好等
有价值信息进行结构化存储。""",
)
async def summarize_session() -> str:
    """总结当前会话并持久化到记忆中。

    Returns:
        总结结果。
    """
    pipeline = await get_pipeline()
    result = await pipeline.run("请总结本次对话的关键要点并记录")
    return result["response"]


@mcp.tool(
    name="analyze_intent",
    description="""分析用户输入的意图类型和关键实体。

Context-OS 支持 8 种意图分类：
- QA: 问答
- CODING: 编程
- DEBUGGING: 调试
- PLANNING: 规划
- SEARCH: 搜索
- WORKFLOW: 工作流
- AGENT: 代理
- DATA_ANALYSIS: 数据分析

此工具使用 LLM 语义分类 + Regex 关键词降级双引擎。""",
)
async def analyze_intent(text: str) -> str:
    """分析用户输入的意图。

    Args:
        text: 用户输入的文本。

    Returns:
        JSON 格式的分析结果，包含 intent、goal、confidence。
    """
    pipeline = await get_pipeline()
    task = await pipeline.task_parser.parse(text)
    return json.dumps(
        {
            "intent": task.intent.value,
            "goal": task.goal.value,
            "confidence": task.confidence,
            "entities": [e.model_dump() for e in task.entities],
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool(
    name="get_memory_stats",
    description="""获取当前记忆系统的统计信息。

包括：
- 各记忆层的条目数量
- 最近写入时间
- 存储空间使用情况

用于诊断和监控记忆系统的健康状态。""",
)
async def get_memory_stats() -> str:
    """获取记忆系统统计信息。

    Returns:
        JSON 格式的统计信息。
    """
    pipeline = await get_pipeline()
    # 记忆统计（memories 表）
    mem_results = await pipeline.store.query(
        "SELECT type, COUNT(*) as cnt FROM memories GROUP BY type"
    )
    counts = {row["type"]: row["cnt"] for row in mem_results} if mem_results else {}

    # 概念统计（concepts 表）
    concept_results = await pipeline.store.query(
        "SELECT COUNT(*) as cnt FROM concepts"
    )
    concept_count = concept_results[0]["cnt"] if concept_results else 0

    # 经验统计（experiences 表）
    exp_results = await pipeline.store.query(
        "SELECT COUNT(*) as cnt FROM experiences"
    )
    experience_count = exp_results[0]["cnt"] if exp_results else 0

    stats = {
        "working_memory_size": len(pipeline.working_memory),
        "session_count": counts.get("session", 0),
        "long_term_count": counts.get("long_term", 0),
        "experience_count": experience_count,
        "concept_count": concept_count,
    }
    return json.dumps(stats, ensure_ascii=False, indent=2)


@mcp.tool(
    name="search_knowledge_graph",
    description="""在知识图谱（语义网络）中查询概念及其关联关系。

当需要了解概念之间的关联时调用，例如：
- "Python 和 FastAPI 是什么关系？"
- "这个项目依赖哪些技术？"

知识图谱通过 BFS 图遍历检索概念关系，不依赖向量相似度。""",
)
async def search_knowledge_graph(concept_name: str, depth: int = 1) -> str:
    """在知识图谱中查询概念。

    Args:
        concept_name: 要查询的概念名称。
        depth: 图遍历深度（1-3），默认 1 层。

    Returns:
        JSON 格式的概念及其关联关系。
    """
    pipeline = await get_pipeline()
    subgraph = await pipeline.semantic_memory.query_graph(
        concept_name, depth=min(depth, 3)
    )
    if subgraph and (subgraph.get("nodes") or subgraph.get("edges")):
        return json.dumps(subgraph, ensure_ascii=False, indent=2)
    return f"未找到概念「{concept_name}」的相关信息"


@mcp.tool(
    name="record_feedback",
    description="""记录用户对 AI 回答或系统行为的反馈。

在以下情况下调用：
1. 用户明确表达满意或不满意
2. 用户指出 AI 回答有误并给出正确答案
3. 用户指示"不要这样做"或"下次这样做"
4. 用户的行为模式发生变化

反馈信息会进入经验记忆（Experience Memory），
用于后续行为调优。""",
)
async def record_feedback(
    feedback_type: str,
    content: str,
) -> str:
    """记录用户反馈。

    Args:
        feedback_type: 反馈类型:
            - "correction": 纠正（用户指出错误并给出正确答案）
            - "preference": 偏好（用户表达喜好变化）
            - "complaint": 不满（用户表示不满意）
            - "praise": 表扬（用户表示满意）
            - "instruction": 指令（用户指示应该如何做）
        content: 反馈内容详情。

    Returns:
        记录结果。
    """
    pipeline = await get_pipeline()
    result = await pipeline.run(
        f"记录一条用户{feedback_type}反馈：{content}"
    )
    return result["response"]


# ═══════════════════════════════════════════════════════════════
# 生命周期事件
# ═══════════════════════════════════════════════════════════════


@mcp.on("startup")
async def on_startup() -> None:
    """服务启动时初始化 Pipeline。"""
    print(f"[context-os] Starting {SERVER_NAME} v{SERVER_VERSION}", file=sys.stderr)
    await get_pipeline()


@mcp.on("shutdown")
async def on_shutdown() -> None:
    """服务关闭时释放资源。"""
    print("[context-os] Shutting down...", file=sys.stderr)
    await close_pipeline()


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    """以 stdio 模式启动 MCP 服务器。

    Claude Code / Trae IDE 通过子进程 stdin/stdout 与此服务器通信。
    不需要 HTTP 端口、不需要独立部署。

    可通过以下方式运行：
        python claude_codex_mcp/server.py
        context-os-mcp  (如果已安装包)
    """
    print(
        f"[context-os] Starting {SERVER_NAME} v{SERVER_VERSION} over stdio...",
        file=sys.stderr,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
