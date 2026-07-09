# Context-OS 记忆系统使用指南

> 本指南详细说明如何使用 Context-OS 的 5 层记忆系统，包括独立使用和通过 Pipeline 自动使用。

---

## 一、5 层记忆概览

| 层级 | 类 | 生命周期 | 存储后端 | 容量/过期 | 核心用途 |
|---|---|---|---|---|---|
| **Working** | `WorkingMemory` | 当前会话 | 纯内存 | Token 上限 8000 | 对话轮次、中间状态 |
| **Short-Term** | `ShortTermMemory` | Session 级 | PostgreSQL | TTL 24h | 会话内历史、临时偏好 |
| **Long-Term** | `LongTermMemory` | 跨 Session | PostgreSQL | 持久（支持遗忘曲线清理） | 用户偏好、项目知识 |
| **Episodic** | `EpisodicMemory` | 跨 Session | PostgreSQL | 持久 | 场景-行动-结果记录 |
| **Semantic** | `SemanticMemory` | 跨 Session | PostgreSQL | 持久 | 知识图谱（概念→关系→概念） |

---

## 二、环境准备

### 2.1 PostgreSQL 依赖（推荐）

绝大多数记忆层依赖 PostgreSQL，配置方式：

```bash
# 设置环境变量
export DATABASE_URL="postgresql://user:password@localhost:5432/context_os"

# 或在 .env 文件中配置
# DATABASE_URL=postgresql://user:password@localhost:5432/context_os
```

**表结构自动创建**：首次调用 `store.connect()` 时自动执行 DDL，无需手动建表。

**pgvector 扩展（可选）**：若需向量检索功能，需安装 `pgvector` 插件：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2.2 无 PostgreSQL 降级模式

若未配置 `DATABASE_URL`，仅有 `WorkingMemory` 可用（纯内存实现），其他记忆层会打印警告并降级为空操作。

---

## 三、独立使用各层记忆

### 3.1 WorkingMemory — 工作记忆

**纯内存实现，无需数据库**，用于当前会话的活跃上下文。

```python
from context_os.memory.working import WorkingMemory

# 创建实例
wm = WorkingMemory(max_tokens=8000)

# 添加记录
item = wm.push(
    content="用户问了一个 K8s 调试问题",
    metadata={"category": "conversation", "intent": "debugging"}
)

# 查询
items = wm.items                    # 获取所有条目
count = wm.item_count               # 条目数量
utilization = wm.token_utilization  # Token 利用率 (0.0-1.0)

# 检查是否接近上限
if wm.token_utilization > 0.9:
    print("工作记忆即将溢出，会自动淘汰最旧条目")
```

**关键特性**：超过 `max_tokens` 时自动淘汰最旧条目，保证内存稳定。

---

### 3.2 ShortTermMemory — 短期记忆

**Session 级持久化**，绑定 Session ID，默认 24 小时过期。

```python
from context_os.memory.short_term import ShortTermMemory
from context_os.memory.store import PostgresStore

# 初始化存储层（需 PostgreSQL）
store = PostgresStore(dsn="postgresql://...")
await store.connect()

# 创建实例
stm = ShortTermMemory(
    session_id="abc123",    # 会话标识
    store=store,
    ttl_hours=24            # 过期时间（小时）
)

# 添加记忆
mem_id = await stm.add(
    content="用户偏好使用中文回答",
    metadata={"category": "preference", "key": "language"},
    user_id="alice"
)

# 检索
memories = await stm.retrieve(
    query="用户偏好",
    top_k=5
)

# 添加任务完成记录（便捷方法）
await stm.add_task_completion(
    task_name="debug: 分析 K8s Crash",
    result="找到原因是内存不足",
    user_id="alice"
)
```

---

### 3.3 LongTermMemory — 长期记忆

**跨 Session 持久化**，支持向量检索和访问频率加权。

```python
from context_os.memory.long_term import LongTermMemory
from context_os.memory.store import PostgresStore

store = PostgresStore(dsn="postgresql://...")
await store.connect()

ltm = LongTermMemory(
    store=store,
    user_id="alice"  # 默认用户 ID
)

# 存储记忆（带向量嵌入）
mem_id = await ltm.store(
    content="项目 X 的代码规范：变量命名使用 snake_case",
    memory_type="project_context",
    metadata={"project": "project_x", "category": "coding_standard"},
    embedding=[0.1, 0.2, 0.3, ...]  # 可选：语义向量
)

# 检索（支持关键词和向量检索）
results = await ltm.retrieve(
    query="代码规范",
    top_k=5,
    memory_type="project_context"  # 可选：按类型过滤
)

# 按用户检索
user_memories = await ltm.retrieve_by_user(
    user_id="alice",
    limit=10
)

# 删除
await ltm.delete(mem_id)
```

**检索机制**：
- 优先使用向量相似度（需 pgvector）
- 降级为关键词匹配
- 结果按相关性 + 时间衰减 + 访问频率综合排序

---

### 3.4 EpisodicMemory — 情景记忆

**记录"场景-行动-结果"故事链**，帮助 Agent 从历史经验中学习。

```python
from context_os.memory.episodic import EpisodicMemory
from context_os.memory.store import PostgresStore

store = PostgresStore(dsn="postgresql://...")
await store.connect()

epm = EpisodicMemory(store=store, user_id="alice")

# 记录成功案例
ep_id = await epm.record_success(
    scene="用户报告 K8s Pod CrashLoopBackOff",
    action="执行 kubectl describe pod 查看事件",
    result="发现 OOMKilled，建议增加内存限制",
    tags=["kubernetes", "debug", "memory"]
)

# 记录失败案例
ep_id = await epm.record_failure(
    scene="用户要求删除所有 Pod",
    action="直接执行 kubectl delete pod --all",
    result="误删生产环境 Pod，被用户投诉",
    feedback="需要增加危险操作确认机制"
)

# 查询历史场景
history = await epm.retrieve(
    scene_query="K8s",
    tags=["debug"],
    limit=10
)

# 查询用户反馈
feedback_list = await epm.retrieve_with_feedback(user_id="alice")
```

---

### 3.5 SemanticMemory — 语义记忆

**知识图谱形式存储概念和关系**，从具体经验中抽象出通用知识。

```python
from context_os.memory.semantic import SemanticMemory
from context_os.memory.store import PostgresStore

store = PostgresStore(dsn="postgresql://...")
await store.connect()

sem = SemanticMemory(store=store, user_id="alice")

# 添加概念
cid = await sem.add_concept(
    name="Kubernetes",
    attributes={
        "定义": "容器编排平台",
        "核心组件": ["Pod", "Service", "Deployment", "ReplicaSet"],
        "常用命令": ["kubectl get", "kubectl describe", "kubectl logs"]
    },
    confidence=0.95
)

# 添加关系（概念之间的关联）
rid = await sem.add_relation(
    source_name="Pod",
    target_name="Deployment",
    relation_type="managed_by",
    weight=0.9
)

# 查询概念
concept = await sem.get_concept("Kubernetes")

# 查询关联概念（知识图谱遍历）
related = await sem.get_related_concepts(
    concept_name="Pod",
    relation_type="managed_by",
    limit=5
)

# 删除关系
await sem.delete_relation(source_name="Pod", target_name="Deployment", relation_type="managed_by")
```

---

## 四、通过 Pipeline 自动使用

在完整 Pipeline 中，记忆系统会**自动执行**以下流程：

```
用户输入 → Pipeline.run()
              │
              ├── 构建阶段：从 LongTermMemory 检索相关记忆
              │
              ├── 执行阶段：LLM 生成回复
              │
              └── 反馈阶段：MemoryUpdater 自动更新所有层级
                      │
                      ├── WorkingMemory  ── 记录当前对话轮次
                      ├── ShortTermMemory ── 记录任务完成
                      ├── LongTermMemory  ── reward_score >= 0.7 才存储
                      ├── EpisodicMemory  ── 记录场景-行动-结果
                      └── SemanticMemory  ── 抽象提炼概念和关系
```

### 4.1 Pipeline 初始化

```python
from context_os.pipeline import ContextOSPipeline
from context_os.llm.openai_client import OpenAIClient

# 创建 LLM 客户端
llm_client = OpenAIClient(api_key="sk-...")

# 创建 Pipeline（自动初始化所有记忆层）
pipeline = ContextOSPipeline(
    llm_client=llm_client,
    provider="openai",
    pg_dsn="postgresql://user:password@localhost:5432/context_os",
    session_id="user_session_001",
    user_id="alice"
)

# 执行
result = await pipeline.run("帮我分析 K8s 集群为什么 CrashLoopBackOff")

# 结果包含评估指标
print(result["metrics"])      # {"answer_quality": 0.92, "reward_score": 0.85, ...}
print(result["latency_ms"])   # 2850.5
```

### 4.2 MemoryUpdater 自动更新规则

见 [memory_updater.py](file:///d:/code/owencli/context_os/feedback/memory_updater.py)：

| 记忆层 | 更新时机 | 更新内容 |
|---|---|---|
| WorkingMemory | 每次执行 | `User: {input}\nAssistant: {response}` |
| ShortTermMemory | 每次执行 | 任务完成记录（名称 + 结果摘要） |
| LongTermMemory | `reward_score >= 0.7` | 完整任务+解决方案（高质量回答才存储） |
| EpisodicMemory | 根据 metrics | 场景-行动-结果链，成功/失败分开记录 |
| SemanticMemory | 根据 metrics | 从对话中抽象概念和关系 |

### 4.3 访问 Pipeline 中的记忆实例

```python
# 通过 Pipeline 实例直接访问各层记忆
wm = pipeline.working_memory
stm = pipeline.short_term_memory
ltm = pipeline.long_term_memory
epm = pipeline.episodic_memory
sem = pipeline.semantic_memory

# 手动添加记忆（与自动更新互补）
await ltm.store(
    content="用户是 K8s 专家，喜欢详细的技术解释",
    metadata={"category": "user_profile", "skill_level": "expert"}
)
```

---

## 五、数据库表结构

见 [store.py](file:///d:/code/owencli/context_os/memory/store.py#L42-L107) 中的 DDL：

```
memories              ─── 统一记忆主表
    id, type, content, embedding[], session_id, user_id,
    timestamp, access_count, relevance_score, metadata(JSONB), expires_at

episodes              ─── 情景记忆表
    id, scene, action, result, feedback, related_files[], tags[], user_id, timestamp

concepts              ─── 语义记忆（概念节点）
    id, name(UNIQUE), attributes(JSONB), embedding[], confidence, user_id, created_at, updated_at

concept_relations     ─── 语义记忆（概念关系）
    id, source_id, target_id, relation_type, weight, created_at
```

---

## 六、已知问题与注意事项

### 6.1 Import Path Bug（待修复）

**问题**：`ShortTermMemory` 的 import 路径不正确：

```python
# 当前代码（错误）
from context_os.core.memory.store import PostgresStore

# 正确路径应为
from context_os.memory.store import PostgresStore
```

**影响**：运行时会报 `ModuleNotFoundError`，需修复 [short_term.py](file:///d:/code/owencli/context_os/memory/short_term.py#L20) 中的 import。

### 6.2 PostgreSQL 连接

- 默认从 `DATABASE_URL` 环境变量读取连接字符串
- 支持懒连接：首次需要时才建立连接池
- 连接池大小：最小 2，最大 10（可配置）

### 6.3 Token 估算

所有记忆层使用简单的字符数 / 4 作为 Token 估算值（与 OpenAI tiktoken 兼容）。

### 6.4 并发安全

当前实现**非线程安全**，建议在 asyncio 单线程环境中使用。

---

## 七、典型使用场景

### 场景 1：用户偏好记忆

```python
# 在用户首次对话时记录偏好
await ltm.store(
    content="用户偏好中文、简洁回答，不喜欢冗长的解释",
    metadata={"category": "user_preference", "user_id": "alice"}
)

# 后续对话自动检索
preferences = await ltm.retrieve(
    query="用户偏好",
    user_id="alice",
    top_k=3
)
```

### 场景 2：项目知识积累

```python
# 记录项目上下文
await ltm.store(
    content="项目架构：采用微服务，技术栈 Python/FastAPI/PostgreSQL",
    metadata={"project": "my_project", "category": "architecture"}
)

# 记录代码规范
await ltm.store(
    content="代码规范：使用 Pydantic 进行数据验证，FastAPI 路由前缀 /api/v1",
    metadata={"project": "my_project", "category": "coding_standard"}
)
```

### 场景 3：错误预防

```python
# 记录过去的错误
await epm.record_failure(
    scene="用户误操作",
    action="执行了危险的删除命令",
    result="数据丢失",
    feedback="需要二次确认机制"
)

# 后续检测到相似场景时提醒
history = await epm.retrieve(scene_query="删除")
if history and any("误操作" in h["scene"] for h in history):
    print("警告：检测到相似的危险操作历史")
```

### 场景 4：知识图谱构建

```python
# 构建领域知识图谱
await sem.add_concept("Docker", attributes={"定义": "容器化平台"})
await sem.add_concept("Kubernetes", attributes={"定义": "容器编排平台"})
await sem.add_relation("Docker", "Kubernetes", "used_by", weight=0.9)
await sem.add_relation("Pod", "Docker", "runs_on", weight=0.8)

# 查询知识图谱
related = await sem.get_related_concepts("Kubernetes", "used_by")
```

---

## 八、模块文件索引

| 文件 | 职责 |
|---|---|
| [store.py](file:///d:/code/owencli/context_os/memory/store.py) | PostgreSQL 存储层，连接池管理，DDL |
| [working.py](file:///d:/code/owencli/context_os/memory/working.py) | 工作记忆（纯内存） |
| [short_term.py](file:///d:/code/owencli/context_os/memory/short_term.py) | 短期记忆（Session 级） |
| [long_term.py](file:///d:/code/owencli/context_os/memory/long_term.py) | 长期记忆（跨 Session） |
| [episodic.py](file:///d:/code/owencli/context_os/memory/episodic.py) | 情景记忆（场景-行动-结果） |
| [semantic.py](file:///d:/code/owencli/context_os/memory/semantic.py) | 语义记忆（知识图谱） |
| [memory_updater.py](file:///d:/code/owencli/context_os/feedback/memory_updater.py) | 记忆更新器，Pipeline 自动更新 |
