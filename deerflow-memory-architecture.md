# DeerFlow Memory Architecture

## Overview

DeerFlow 的 memory 系统是一个**基于 LLM 的持久化记忆机制**。它通过提取对话中的事实信息并注入后续对话的系统提示，为 Agent 提供个性化的上下文感知能力。整套机制是一个闭环的持续学习系统。

```
Conversation ──▶ MemoryMiddleware ──▶ Message Filtering ──▶ Signal Detection
                                                                │
                                                                ▼
                                                     MemoryUpdateQueue
                                                     (Debounce 30s)
                                                                │
                                                                ▼
                                                     LLM Summarization
                                                     (MEMORY_UPDATE_PROMPT)
                                                                │
                                                                ▼
                                                     memory.json (persist)
                                                                │
                                                                ▼
                                              Next conversation injection
                                              (format_memory_for_injection)
```

---

## 1. Configuration — `config/memory_config.py`

Memory 系统的行为由 `MemoryConfig` 控制。

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | 总开关 |
| `storage_path` | `""` | 存储路径。空值 = 按用户隔离 (`{base_dir}/users/{user_id}/memory.json`)；绝对路径 = 所有用户共享 |
| `storage_class` | `"deerflow.agents.memory.storage.FileMemoryStorage"` | 存储实现类，可插拔 |
| `debounce_seconds` | `30` | 防抖窗口（秒），窗口内同一 thread 的多次更新合并为一次 LLM 调用 |
| `model_name` | `null` | 记忆更新专用模型，默认使用系统默认模型 |
| `max_facts` | `100` | 最大存储事实数 |
| `fact_confidence_threshold` | `0.7` | 事实入库的最低置信度 |
| `injection_enabled` | `true` | 是否将记忆注入系统提示 |
| `max_injection_tokens` | `2000` | 注入时的 token 预算上限 |

---

## 2. Data Structure — `agents/memory/storage.py`

记忆以 JSON 文件持久化，结构如下：

```json
{
  "version": "1.0",
  "lastUpdated": "2026-06-24T12:00:00Z",
  "user": {
    "workContext":     { "summary": "...", "updatedAt": "..." },
    "personalContext": { "summary": "...", "updatedAt": "..." },
    "topOfMind":      { "summary": "...", "updatedAt": "..." }
  },
  "history": {
    "recentMonths":       { "summary": "...", "updatedAt": "..." },
    "earlierContext":     { "summary": "...", "updatedAt": "..." },
    "longTermBackground": { "summary": "...", "updatedAt": "..." }
  },
  "facts": [
    {
      "id": "fact_a1b2c3d4",
      "content": "User is a backend architect at ByteDance",
      "category": "context",
      "confidence": 0.95,
      "createdAt": "2026-06-24T12:00:00Z",
      "source": "thread_xxx",
      "sourceError": "optional, only for correction facts"
    }
  ]
}
```

### 2.1 `user` 区 — 用户当前状态

| 字段 | 长度 | 说明 |
|------|------|------|
| `workContext` | 1-3 句 | 当前职业角色、公司、主要项目和技术栈 |
| `personalContext` | 1-2 句 | 语言能力、沟通偏好、核心兴趣 |
| `topOfMind` | 3-5 句 | 多个并发的关注点和优先级（最常更新） |

### 2.2 `history` 区 — 时间维度记忆

| 字段 | 时间跨度 | 长度 | 说明 |
|------|----------|------|------|
| `recentMonths` | 近 1-3 个月 | 4-6 句或 1-2 段 | 近期技术探索和工作详情 |
| `earlierContext` | 3-12 个月前 | 3-5 句或 1 段 | 过去项目、学习经历 |
| `longTermBackground` | 长期/整体 | 2-4 句 | 核心专长、基本工作风格 |

### 2.3 `facts` 区 — 细粒度事实

每个事实包含：
- `id` — 唯一标识（UUID hex 前 8 位）
- `content` — 事实内容
- `category` — 类别（见下表）
- `confidence` — LLM 给出的置信度 [0, 1]
- `createdAt` — 创建时间
- `source` — 来源 thread_id
- `sourceError` — （可选）仅用于 correction 类别，记录错误根源

#### 事实类别

| Category | 说明 |
|----------|------|
| `preference` | 用户偏好（工具、风格、方法） |
| `knowledge` | 专业知识、掌握的技术 |
| `context` | 背景事实（职位、项目、语言） |
| `behavior` | 工作模式、沟通习惯 |
| `goal` | 目标、学习方向 |
| `correction` | Agent 错误或用户纠正 |

---

## 3. Storage Layer — `agents/memory/storage.py`

### 3.1 类层次

```
MemoryStorage (ABC)
    └── FileMemoryStorage (default)
```

- **`MemoryStorage`** — 抽象基类，定义 `load / reload / save` 接口
- **`FileMemoryStorage`** — JSON 文件实现

### 3.2 文件路径策略

按优先级降序：

1. **user_id + agent_name**: `{base_dir}/users/{user_id}/agents/{agent_name}/memory.json`
2. **user_id only**: `{base_dir}/users/{user_id}/memory.json`
3. **agent_name only**: `{base_dir}/agents/{agent_name}/memory.json`
4. **全局（无 user_id 无 agent_name）**: `{base_dir}/memory.json` 或 `config.storage_path`

### 3.3 缓存的优化

- 使用 `(user_id, agent_name)` 元组作为缓存键
- **双重校验**：缓存命中时，检查文件 mtime 是否变化；仅当 mtime 匹配时才返回缓存
- 写操作后主动更新缓存

### 3.4 原子写入

```python
temp_path = file_path.with_suffix(f".{uuid4().hex}.tmp")
with open(temp_path, "w") as f:
    json.dump(memory_data, f)
temp_path.replace(file_path)  # atomic rename
```

先写临时文件再 rename，防止写入中断导致数据损坏。

### 3.5 可插拔存储

通过 `config.storage_class` 可以替换存储实现（需继承 `MemoryStorage`），例如切换到 Redis 或数据库存储。

---

## 4. Queue & Debounce — `agents/memory/queue.py`

### 4.1 MemoryUpdateQueue

全局单例，核心机制：

```
add(thread_id, messages)
    │
    ▼
[LOCK] _enqueue_locked()
    │  - 相同 (thread_id, user_id, agent_name) 的条目合并
    │  - correction_detected / reinforcement_detected 合并取 OR
    │
    ▼
_reset_timer()
    │  - 取消旧 timer
    │  - 设置新 timer = debounce_seconds（默认 30s）
    │
    ▼（timer 触发）
_process_queue()
    │  - [LOCK] 取出全部队列
    │  - 对每个 context 调用 MemoryUpdater.update_memory()
    │  - 使用 ThreadPoolExecutor(max_workers=4) 隔离 LLM 调用
    │  - 每个 context 间隔 0.5s 避免限流
```

### 4.2 关键方法

| 方法 | 说明 |
|------|------|
| `add()` | 加入队列，重置防抖 timer |
| `add_nowait()` | 加入队列并立即处理（timer=0） |
| `flush()` | 强制立即处理（同步） |
| `flush_nowait()` | 强制立即处理（后台线程） |
| `clear()` | 清空队列 |

### 4.3 线程安全

- `threading.Lock` 保护所有队列操作
- `threading.Timer` 作为防抖定时器（daemon=True）
- 用户 ID 在 enqueue 时通过参数显式传入，避免 ContextVar 跨线程丢失

---

## 5. LLM Memory Update — `agents/memory/updater.py` + `prompt.py`

### 5.1 MemoryUpdater

核心流程：

```
_prepare_update_prompt()
    │  1. get_memory_data() 加载当前记忆
    │  2. format_conversation_for_update() 格式化对话
    │  3. 构造 MEMORY_UPDATE_PROMPT
    │
    ▼
model.invoke(prompt)
    │  LLM 返回 JSON（含 user/history 各段 shouldUpdate + newFacts + factsToRemove）
    │
    ▼
_finalize_update()
    │  1. _parse_memory_update_response() — 正则提取 JSON
    │  2. _apply_updates() — 合并到当前记忆
    │  3. _strip_upload_mentions_from_memory() — 清除文件上传事件
    │  4. get_memory_storage().save() 持久化
```

### 5.2 MEMORY_UPDATE_PROMPT 核心指令

LLM 被要求执行结构化分析：

1. **自我反思**：
   - 检测 agent 自身的错误/重试 → 记录为 `category="correction"`，置信度 ≥ 0.95
   - 检测用户的纠正 → 记录为 `category="correction"`，包含 `sourceError`
   - 检测项目约束发现

2. **各区段更新**：
   - 每个区段通过 `shouldUpdate` 字段标记是否需要更新
   - 只在实际有新信息时才更新，避免无效写入

3. **事实提取**：
   - 保留具体量化和专有名词
   - 按置信度等级打分（详见第 6 节）
   - 对重复事实去重（通过内容 casefold 比较）

4. **特殊规则**：
   - 不记录文件上传事件（`_strip_upload_mentions_from_memory`）
   - `sourceError` 仅用于 `correction` 类别

### 5.3 线程模型

| 调用上下文 | 执行方式 |
|-----------|---------|
| 同步上下文 | 直接 `model.invoke()` |
| 异步上下文（有 running loop） | `ThreadPoolExecutor.submit()` 卸载到线程 |
| 异步方法 `aupdate_memory()` | `asyncio.to_thread()` 委托到线程 |

分离线程池的目的是**避免与主 Agent 共享 httpx AsyncClient 连接池**，防止跨事件循环的连接复用 bug。

### 5.4 _apply_updates 细节

- **用户区**: 仅当 `shouldUpdate=true` 且 `summary` 非空时覆盖
- **历史区**: 同上
- **事实删除**: 匹配 `fact.id` 移除
- **事实新增**:
  - 内容去重（casefold 比较）
  - 过滤 `confidence < fact_confidence_threshold`（默认 0.7）的事实
  - 超过 `max_facts` 时按置信度降序截断

---

## 6. Confidence System — 置信度机制

### 6.1 LLM 生成（非计算）

置信度完全由 LLM 根据 prompt 中的三段式规则**语义判断**生成，没有统计计算：

| Range | Meaning | Example |
|-------|---------|---------|
| **0.9 - 1.0** | Explicitly stated | "I work at ByteDance", "My role is architect" |
| **0.7 - 0.8** | Strongly implied | User discusses Go performance optimization repeatedly |
| **0.5 - 0.6** | Inferred pattern (use sparingly) | Behavioral pattern with clear evidence |

### 6.2 信号增强

| Signal | Detection | Confidence override |
|--------|-----------|-------------------|
| Correction | "不对"、"你理解错了"、"try again" | ≥ 0.95, category="correction" |
| Reinforcement | "就是这样"、"完全正确"、"keep doing that" | ≥ 0.9, category="preference/behavior" |

### 6.3 置信度在系统中的生命周期

```
LLM 生成 confidence
    │
    ▼
_normalize_memory_update_fact()
    │  校验类型、去除非有限值
    │
    ▼
_apply_updates()
    │  confidence ≥ fact_confidence_threshold (0.7) → 入库
    │  confidence < 0.7 → 丢弃
    │
    ▼
超 max_facts(100) 时
    │  按 confidence 降序截断
    │
    ▼
format_memory_for_injection()
    按 confidence 降序排列，高置信度优先进入 token 预算
```

---

## 7. Middleware Integration — `agents/middlewares/memory_middleware.py`

### 7.1 MemoryMiddleware

LangGraph `AgentMiddleware` 实现，在 `after_agent()` 钩子中触发。

```
after_agent(state, runtime)
    │
    ▼
1. 获取 thread_id（runtime.context → LangGraph config → 跳过）
    │
    ▼
2. 获取 messages（state["messages"]）
    │
    ▼
3. filter_messages_for_memory(messages)
    │  - 保留 human + 最终 ai 消息
    │  - 移除 tool_calls / tool 消息
    │  - 移除仅有文件上传的 human 消息
    │
    ▼
4. detect_correction(filtered_messages)
    │  正则匹配 _CORRECTION_PATTERNS
    │
5. detect_reinforcement(filtered_messages)
    │  正则匹配 _REINFORCEMENT_PATTERNS
    │
    ▼
6. get_memory_queue().add(...) 入队
```

### 7.2 信号检测正则

- **Correction patterns** (中英双语):
  - `that(?:'s| is) (?:wrong|incorrect)`
  - `you misunderstood`, `try again`, `redo`
  - `不对`, `你理解错了`, `重试`, `重新来`, `换一种`, `改用`

- **Reinforcement patterns** (中英双语):
  - `yes, exactly`, `that's right/correct`, `perfect`, `keep doing that`
  - `对，就是这样`, `完全正确`, `就是这个意思`, `正是我想要的`, `继续保持`

---

## 8. Summarization Hook — `agents/memory/summarization_hook.py`

### 8.1 memory_flush_hook

当 LangGraph 的 SummarizationMiddleware 准备压缩历史消息时，该 hook 被触发：

```
summarization 即将删除消息
    │
    ▼
memory_flush_hook(event)
    │  1. 过滤消息
    │  2. 检测 correction/reinforcement 信号
    │  3. queue.add_nowait() 立即处理（不经过防抖）
    │
    ▼
保存后 summarization 再删除消息
```

目的是在消息被 summarization 吞掉之前，先将其内容送入 memory 系统，**防止数据丢失**。

---

## 9. Memory Injection — `agents/lead_agent/prompt.py`

### 9.1 _get_memory_context

每次对话构建系统提示时被调用：

```
_get_memory_context(agent_name)
    │
    ▼
1. 检查 config.enabled && config.injection_enabled → 否则返回空
    │
    ▼
2. get_memory_data(agent_name, user_id)
    │
    ▼
3. format_memory_for_injection(memory_data, max_tokens)
    │  - 格式化 user 三个字段
    │  - 格式化 history 三个字段
    │  - 事实按 confidence 降序排列，逐个加入
    │  - tiktoken 精确计数，超 max_injection_tokens 截断
    │  - correction 事实附带 sourceError 显示 "(avoid: ...)"
    │
    ▼
4. 包装为 <memory>...</memory> XML 标签注入系统 prompt
```

### 9.2 注入格式示例

```xml
<system-reminder>
<memory>
User Context:
- Work: Core contributor to an open-source agent framework (16k+ stars)
- Personal: Bilingual (Chinese/English), interested in LLM agent systems
- Current Focus: Building memory system for persistent user context

History:
- Recent: Designed and implemented LLM-based memory extraction pipeline
- Background: Experienced in Python backend, LangGraph, FastAPI

Facts:
- [context | 0.95] User is a backend architect at ByteDance
- [preference | 0.90] Prefers Python type hints and Pydantic for config
- [correction | 0.95] Agent should not record file upload events in memory
</memory>

<current_date>2026-06-24, Tuesday</current_date>
</system-reminder>
```

---

## 10. Memory CRUD API — `updater.py` (exposed via `client.py`)

| API | Description |
|-----|-------------|
| `get_memory_data(agent_name, user_id)` | 加载记忆数据（含缓存） |
| `reload_memory_data(agent_name, user_id)` | 强制重载（刷新缓存） |
| `import_memory_data(data, agent_name, user_id)` | 导入并持久化完整记忆 |
| `clear_memory_data(agent_name, user_id)` | 清空记忆（写回空结构） |
| `create_memory_fact(content, category, confidence)` | 手动创建单条事实 |
| `delete_memory_fact(fact_id)` | 按 ID 删除事实 |
| `update_memory_fact(fact_id, content, category, confidence)` | 更新已有事实 |

这些 API 在 `DeerFlowClient` 中暴露，支持编程式访问。

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                       LangGraph Agent Runtime                        │
│                                                                     │
│  ┌─────────────────┐      ┌──────────────────────────────┐         │
│  │  Lead Agent      │      │  MemoryMiddleware            │         │
│  │  (prompt)        │──────▶  after_agent()              │         │
│  │  injection ◀─────│      │  ─────────────────────────   │         │
│  │                   │      │  1. filter_messages()      │         │
│  │                   │      │  2. detect_signals()       │         │
│  │                   │      │  3. queue.add()            │         │
│  └─────────────────┘      └───────────┬──────────────────┘         │
│                                       │                            │
│  ┌─────────────────┐      ┌───────────▼──────────────────┐         │
│  │ Summarization   │      │  MemoryUpdateQueue            │         │
│  │ Middleware       │      │  (debounce 30s, ThreadPool)  │         │
│  │                  │      │                               │         │
│  │ memory_flush_hook│──────▶  _process_queue()            │         │
│  │ (before delete)  │      │       │                      │         │
│  └─────────────────┘      └───────┼───────────────────────┘         │
│                                   │                                │
└───────────────────────────────────┼────────────────────────────────┘
                                    │
                                    ▼
                        ┌─────────────────────────┐
                        │  MemoryUpdater           │
                        │                         │
                        │  1. prepare_prompt      │
                        │  2. LLM invoke()        │
                        │  3. apply_updates()     │
                        │  4. save()              │
                        └─────────────┬───────────┘
                                      │
                                      ▼
                        ┌─────────────────────────┐
                        │  FileMemoryStorage       │
                        │  (atomic write, cache)   │
                        │                         │
                        │  memory.json             │
                        └─────────────────────────┘
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **LLM-driven extraction** | 利用 LLM 的语义理解能力自然提取结构化记忆，避免手工规则 |
| **Debounced queue** | 减少频繁更新导致的 LLM 调用开销，同时保证最终一致性 |
| **Separate thread pool for memory** | 避免与主 Agent 共享 httpx 连接池，防止跨事件循环 bug |
| **Atomic file write** | 防止写入中断导致 memory.json 损坏 |
| **Content-based fact dedup** | 基于 casefold 内容去重，防止同一事实反复入库 |
| **Upload mention scrubbing** | 文件上传是 session 级的，持久化会导致后续对话错误引用 |
| **Correction/Reinforcement signals** | 让用户反馈直接影响记忆更新的置信度 |
| **Per-user / per-agent isolation** | 多用户多 Agent 场景下记忆隔离，路径天然分治 |
