```
                User Request
                     │
                     ▼
          ① Intent Understanding
                     │
                     ▼
          ② Context Orchestrator
                     │
                     ▼
          ③ Context Collection
                     │
                     ▼
           ④ Context Builder
                     │
                     ▼
          ⑤ Context Optimization
                     │
                     ▼
          ⑥ Context Packaging
                     │
                     ▼
                 LLM Inference
                     │
                     ▼
            Tool / Agent Execute
                     │
                     ▼
           ⑦ Context Feedback
                     │
                     └───────────────► Memory Update
```

**生命周期总览：**

```
Understand → Collect → Build → Optimize → Execute → Learn
```

整个 Context 在系统中不断演化，而不是一次性的 Prompt。

---

## ① Intent Understanding（意图理解）

将用户自然语言转换成系统能够理解的任务描述（Task）。

### 输入示例

```
User:
帮我分析 Kubernetes 集群为什么一直 CrashLoopBackOff
```

### 输出示例

```yaml
Intent:
    Diagnose Kubernetes Failure

Goal:
    Root Cause Analysis

Task Type:
    Troubleshooting

Domain:
    Kubernetes

Need Tool:
    - kubectl
    - Prometheus
    - MCP

Need Knowledge:
    - K8s Docs

Priority:
    High
```

### 核心能力


| 能力                      | 说明                                                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| **Intent Classification** | 识别任务类型：QA / Coding / Planning / Debugging / Search / Workflow / Agent / Data Analysis |
| **Entity Extraction**     | 提取实体：Cluster / Namespace / Pod / Deployment / Node                                      |
| **Parameter Extraction**  | 提取参数：`namespace=prod` `pod=nginx` `cluster=test` `time=1h`                              |
| **Goal Understanding**    | 明确真正目标：Fix / Explain / Generate / Summarize / Compare                                 |

### 输出

```typescript
interface TaskSpec {
  intent: string;
  goal: string;
  entity: Entity[];
  constraint: Constraint;
  priority: number;
  toolRequirement: ToolRequirement[];
  knowledgeRequirement: KnowledgeRequirement[];
}
```

---

## ② Context Orchestrator（上下文编排）

整个系统的大脑。决定需要哪些 Context，而不是全部拿出来。

### 职责

- **Route Context** — 路由到正确的 Context 源
- **Select Context** — 只选择当前任务需要的 Context
- **Prioritize Context** — 按优先级排序
- **Merge Context** — 合并多个 Context 源

### 示例

```
Task: Debug Kubernetes
  │
  Need:
  ├── Identity Context
  ├── Conversation Context
  ├── Environment Context
  ├── Memory
  ├── Knowledge
  └── Tools

Task: Write Email
  │
  Skip:
  └── Environment Context  ← 不需要
```

**核心思想：Dynamic Context Selection**

---

## ③ Context Collection（上下文收集）

### Identity Context

提供"用户是谁"的信息。

```yaml
User Profile:
  Role: Platform Engineer
  Permission: Cluster Admin
  Language: Chinese
  Skill Level: Advanced

Organization:
  Tenant: acme-corp
  Team: platform-engineering
```

### Conversation Context

当前任务的状态与历史。

```yaml
History:
  - Turn 1: "检查集群状态"
  - Turn 2: "查看 CrashLoopBackOff pod"

Current:
  Topic: Kubernetes Failure
  Step: 4/10
  Status: Waiting MCP Result

Task Graph:
  - Analyze Pod Status
  - Check Resource Limits
  - Inspect Logs
  - Verify Network Policy
```

### Environment Context

描述系统运行环境。这是传统 Prompt 没有的部分。

```yaml
Cluster: dev
Namespace: agent-system
Current Workspace: /projects/owencli
Git Branch: feature/context
Runtime:
  OS: Linux
  CPU: x86_64
  Memory: 16GB
MCP Server: localhost:8080
```

---

## ④ Context Builder

真正构建 Prompt 的地方，但不是简单拼接。

### 核心流程

```
Builder
├── Merge        — 合并多个 Context 源
├── Normalize    — 统一格式
├── Deduplicate  — 去重
├── Validate     — 校验完整性
└── Transform    — 格式转换
```

### 三大输入来源

#### Memory（长期记忆）

```yaml
User Memory:
  - 用户一直在开发 Agent
  - 喜欢 Mermaid 图表
  - 使用 Kubernetes

Task Memory:
  - 上次调试过 K8s 网络问题
  - 使用了 Prometheus 查询

Semantic Memory:
  - Kubernetes 故障排查方法论

Episode Memory:
  - 2026-06-17: 排查 CrashLoopBackOff → 定位为 OOMKill
```

#### Knowledge（外部知识）

```yaml
Sources:
  - Vector DB (RAG)
  - Document / Wiki
  - API Docs
  - Code Base

Retrieval:
  TopK: 5
  Chunk Size: 512
  Merge Strategy: concat
```

#### Tool Context（工具上下文）

```yaml
MCP:
  - kubectl
    Args: ["get", "pods"]
    Permission: readonly
    Current Cluster: dev

  - Prometheus
    Query: "container_memory_usage_bytes"
    Time Range: "1h"
```

### 最终输出

```typescript
interface UnifiedContext {
  identity: IdentityContext;
  conversation: ConversationContext;
  environment: EnvironmentContext;
  memory: MemoryContext;
  knowledge: KnowledgeContext[];
  tools: ToolContext[];
}
```

---

## ⑤ Context Optimizer

Context Engineering **最重要**的一层。LLM 最大瓶颈是 Token，所以必须优化。

### Compression（压缩）


| 方法                     | 说明                     |
| ------------------------ | ------------------------ |
| **Summary**              | 直接摘要                 |
| **Hierarchy Summary**    | 分层摘要                 |
| **Recursive Summary**    | 递归摘要                 |
| **Semantic Compression** | 语义压缩（保留关键信息） |

### Ranking（排序）

```typescript
interface RankingScore {
  taskRelevance: number;      // 与当前任务的相关性
  timeRelevance: number;      // 时间衰减
  semanticSimilarity: number; // 语义相似度
  priority: number;           // 显式优先级
}

// Top Context = TopK by combined score
```

### Token Budget（预算控制）

根据不同模型能力自动分配 Token 比例：


| 模块        | 占比 |
| ----------- | ---- |
| History     | 20%  |
| Memory      | 10%  |
| Knowledge   | 45%  |
| Tool        | 15%  |
| Instruction | 10%  |

支持模型：128K / 64K / 32K 自动适配。

### 输出

```typescript
interface OptimizedContext {
  compressed: boolean;
  tokenUsage: TokenBudget;
  context: UnifiedContext;  // 精简后
}
```

---

## ⑥ Context Packager

Builder 得到的是 **Object**，LLM 不能直接理解，需要包装成 LLM 可读的格式。

### 包装格式

```
system:
    [系统指令]

memory:
    [记忆信息]

knowledge:
    [知识信息]

tools:
    [工具定义]

conversation:
    [对话历史]
```

支持多种序列化格式：

- JSON
- XML
- Markdown
- Prompt Template

### 模型适配

这一层完全与模型解耦，不同模型拥有自己的 **Prompt Adapter**：

```
GPT      → JSON-based Adapter
Claude   → XML-based Adapter
Gemini   → Markdown-based Adapter
Qwen     → ChatML-based Adapter
DeepSeek → Custom Adapter
```

---

## ⑦ LLM Inference

模型真正开始推理。

### 推理能力

- **Reasoning** — 链式推理
- **Planning** — 任务规划
- **Tool Calling** — 工具调用
- **Function Calling** — 函数调用
- **Multi-Agent Planning** — 多 Agent 协作
- **Code Generation** — 代码生成

这一层只负责 **Thinking**，不会管理 Context。

---

## ⑧ Context Feedback

这一层决定系统是否越来越聪明。

### Memory Update

更新长期记忆：

```yaml
Write to Long Memory:
  - 新的用户偏好
  - 新的任务经验
  - 新的事实
```

### Evaluation

```yaml
Metrics:
  Answer Quality: 0.92
  Hallucination Score: 0.03
  Tool Accuracy: 0.98
  Latency: 2.3s
  Cost: $0.04
  Success Rate: 95%

Reward Score: 0.94  # 用于后续优化
```

### Trace

完整记录所有执行信息：

```
Trace
├── Prompt (原始 + 优化后)
├── Context (所有输入源)
├── Tool Calls (调用链)
├── Latency (每步耗时)
├── Token (消耗量)
├── Reasoning (推理过程)
├── Memory (使用/更新)
└── Knowledge (检索记录)
```

集成可观测性工具：

- LangSmith
- OpenTelemetry
- Phoenix
- Arize

用于：**Debug / Replay / Evaluation / Fine-tuning**

---

## 整体执行流程（End-to-End Flow）

```
User
 │
 ▼
Intent Understanding
 │
 ├─ Intent Classification
 ├─ Goal Recognition
 ├─ Entity Extraction
 └─ Task Specification
 │
 ▼
Context Orchestrator
 │
 ├─ Select Identity Context
 ├─ Select Conversation Context
 ├─ Select Environment Context
 ├─ Select Memory
 ├─ Select Knowledge
 └─ Select Tool Context
 │
 ▼
Context Builder
 │
 ├─ Merge
 ├─ Normalize
 ├─ Deduplicate
 ├─ Retrieve RAG
 ├─ Load Memory
 └─ Load MCP Metadata
 │
 ▼
Context Optimizer
 │
 ├─ Rank
 ├─ Compress
 ├─ Token Budget Allocation
 └─ Relevance Filtering
 │
 ▼
Context Packager
 │
 ├─ System Prompt
 ├─ Memory Section
 ├─ Knowledge Section
 ├─ Tool Section
 └─ Conversation Section
 │
 ▼
LLM
 │
 ├─ Reasoning
 ├─ Planning
 ├─ Tool Calling
 └─ Response Generation
 │
 ▼
Execution & Feedback
 │
 ├─ Update Memory
 ├─ Evaluate Quality
 ├─ Store Trace
 └─ Optimize Future Context
```

---

## 技术选型建议


| 模块       | 推荐技术                  | 备选             |
| ---------- | ------------------------- | ---------------- |
| 核心语言   | Python                    | Rust / Go        |
| LLM 调用   | Anthropic SDK             | 自研 LLM Gateway |
| 向量数据库 | Chroma / Qdrant           | Milvus / FAISS   |
| 关系数据库 | PostgreSQL                | MySQL            |
| 知识图谱   | Neo4j                    | Memgraph         |
| 序列化     | MessagePack / JSON        | Protobuf         |
| 缓存       | Redis                     | Memcached        |
| 任务队列   | BullMQ / Celery           | RabbitMQ         |
| 可观测性   | OpenTelemetry + LangSmith | Phoenix / Arize  |

---

## 路线图

### Phase 1 — 基础 Pipeline

- [ ]  Intent Understanding 引擎
- [ ]  Context Orchestrator 动态选择
- [ ]  基础 Context Collection（Identity + Conversation）

### Phase 2 — 智能 Context 管理

- [ ]  Context Builder 完整实现
- [ ]  Context Optimizer（压缩 + 排序 + Token Budget）
- [ ]  Context Packager 多模型适配

### Phase 3 — 记忆与知识

- [ ]  Memory 长期记忆持久化
- [ ]  RAG Knowledge 集成
- [ ]  Tool Context（MCP 协议）

### Phase 4 — 学习与进化

- [ ]  Context Feedback 自动评估
- [ ]  Trace & Replay 系统
- [ ]  基于反馈的 Context 自优化
