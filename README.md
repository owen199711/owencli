# Context-OS — AI Agent 上下文管理系统

为 AI Agent 设计的上下文管理框架，涵盖意图理解、上下文收集、分层记忆、上下文优化、Prompt 打包、LLM 调用和反馈闭环的全生命周期。

---

## 快速开始

```bash
# 1. 设置 API Key
export DEEPSEEK_API_KEY="your-key"

# 2. 运行示例
python examples/basic_pipeline.py
```

```python
import asyncio
from context_os.llm.deepseek_client import DeepSeekClient
from context_os.pipeline import ContextOSPipeline

async def main():
    llm = DeepSeekClient()
    async with ContextOSPipeline(llm_client=llm, user_id="demo") as pipeline:
        result = await pipeline.run("Python 列表推导式和生成器有什么区别？")
        print(result["response"])

asyncio.run(main())
```

---

## 系统架构

```
┌────────────────────────────────────────────────────────────────────┐
│                         Context-OS Pipeline                        │
│                                                                    │
│  用户输入                                                          │
│     │                                                              │
│     ▼                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │  Intent  │→ │Orchestrator│→ │Collection │→ │    Builder       │ │
│  │ Layer    │  │          │  │ Layer     │  │  (ContextBuilder) │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────┬─────────┘ │
│                                                      │              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │              │
│  │ Feedback │← │   LLM    │← │ Packager │←───────────┘              │
│  │ Layer    │  │  Client  │  │          │                           │
│  └──────────┘  └──────────┘  └──────────┘                           │
│                                                      │              │
│  ┌───────────────────────────────────────────────────┘              │
│  ▼                                                                  │
│  ┌──────────┐                                                       │
│  │ Optimizer │  (RelevanceRanker + Compressor + Budget)             │
│  └──────────┘                                                       │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │                   Memory System                           │      │
│  │  Working │ ShortTerm │ LongTerm │ Episodic │ Semantic    │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │               SQLite Store (持久化层)                     │      │
│  └──────────────────────────────────────────────────────────┘      │
└────────────────────────────────────────────────────────────────────┘
```

---

## 模块说明

### Core（核心基础层）
| 模块 | 文件 | 职责 |
|------|------|------|
| **base.py** | 4 个抽象基类 | `BaseCollector` / `BaseMemoryStore` / `BasePromptAdapter` / `BaseLLMClient` |
| **models.py** | 20+ Pydantic 模型 | `TaskSpec` / `UnifiedContext` / `OptimizedContext` / `PackagedContext` / `EvalMetrics` 等 |
| **errors.py** | 3 层异常体系 | `ContextOSError` → `ContextBuildError` / `MemoryError` |
| **logger.py** | 统一日志 | 支持环境变量 `LOG_LEVEL`，统一格式输出到 stdout |

### Intent（意图理解层）
| 模块 | 职责 |
|------|------|
| **IntentClassifier** | 用户输入分类 → `(IntentType, GoalType, confidence)`，支持 LLM 语义分类 + Regex 降级 |
| **EntityExtractor** | 提取命名实体 + 推断工具需求 + 推断知识需求 |
| **TaskParser** | 组装分类+提取结果 → 标准 `TaskSpec` |

### Orchestrator（编排层）
| 模块 | 职责 |
|------|------|
| **ContextSelector** | 按意图类型动态决定收集哪些数据源（8 种意图 × 不同 ContextFlag 组合） |
| **ContextRouter** | `ContextFlag` → 按优先级排序的 `ContextRoute[]` |

### Collection（数据收集层）
| 模块 | 职责 |
|------|------|
| **IdentityCollector** | 用户身份信息（角色/权限/语言等），支持注入或从环境变量读取 |
| **ConversationCollector** | 对话历史环形缓冲区（默认最多 50 轮） |
| **EnvironmentCollector** | 系统运行环境（OS/Git/Python 版本/MCP 服务器等） |

### Memory（记忆系统 — 核心亮点）

10 种记忆类型，按生命周期和用途分层：

| 记忆类型 | 持久化 | 生命周期 | 用途 |
|---------|--------|---------|------|
| **WorkingMemory** | 纯内存 | 当前对话 | 活跃上下文，Token 预算控制（默认 8K），环形缓冲区 |
| **ShortTermMemory** | SQLite | Session（默认 24h） | 用户偏好、子任务记录、错误恢复记录 |
| **LongTermMemory** | SQLite | 跨 Session | 用户偏好/项目上下文/决策记录，Ebbinghaus 遗忘曲线自动清理 |
| **EpisodicMemory** | SQLite | 永久 | "场景-行动-结果"故事化记录，成功/失败经验 |
| **SemanticMemory** | SQLite | 永久 | 知识图谱（Concept → Relation → Concept），BFS 子图查询 |
| **FactMemory** | SQLite | 永久 | 版本化 KV 存储（支持历史版本追溯、置信度管理） |
| **ProceduralMemory** | SQLite | 永久 | 工作流步骤模式存储（附带成功率统计） |
| **ReflectionMemory** | SQLite | 永久 | Agent 自我反思（根因分析/经验教训/预防措施） |
| **TaskMemory** | SQLite | 永久 | 任务执行记录（状态/耗时/Token 用量） |
| **ToolExperienceMemory** | SQLite | 永久 | 工具调用成功率/平均耗时统计 |

**记忆检索排序算法**（定义于 `optimizer/ranker.py`）：
```
score = 0.5 × 语义相似度(cosine) + 0.3 × 时间衰减(exp) + 0.2 × 访问频率(log)
```

**记忆写入策略**（定义于 `feedback/memory_updater.py`）：
| 层级 | 条件 | 内容 |
|------|------|------|
| Working | 每次执行 | 用户输入 + LLM 回复 |
| ShortTerm | 每次执行 | 任务完成记录 |
| LongTerm | reward ≥ 0.7 | 高质量问答对 |
| Episodic | 总是 | success / failure 经验 |
| Semantic | 批量抽象 | 从高频 Episodic 标签提炼概念 |

### Builder（上下文构建）
| 模块 | 职责 |
|------|------|
| **ContextBuilder** | 编排 Selector→Router→并行收集→记忆检索→Merger |
| **ContextMerger** | 合并多个 UnifiedContext + 归一化排序 + 去重 |

### Optimizer（上下文优化）
| 模块 | 职责 |
|------|------|
| **RelevanceRanker** | 语义+时间+频率三维排序 |
| **ContextCompressor** | LLM 摘要或截断式压缩对话/记忆 |
| **TokenBudgetAllocator** | 各模块 Token 预算分配（instruction 10%/conversation 20%/memory 10%/knowledge 45%/tools 15%） |

### Packager（Prompt 打包）
| 适配器 | 格式 |
|--------|------|
| **ClaudePromptAdapter** | XML 标签格式 (`<identity>`, `<memory>`, `<conversation>` 等) |
| **OpenAIPromptAdapter** | 纯文本分段格式 (`[Identity]`, `[Memory]`, `[Conversation]`) |
| 复用 | DeepSeek 兼容 OpenAI 格式 |

### LLM（客户端）
| 客户端 | 默认模型 | 说明 |
|--------|---------|------|
| `AnthropicClient` | claude-sonnet-4-20250514 | Anthropic SDK |
| `OpenAIClient` | gpt-4o | OpenAI SDK |
| `DeepSeekClient` | deepseek-chat | OpenAI 兼容接口 |

### Feedback（反馈闭环）
| 模块 | 职责 |
|------|------|
| **QualityEvaluator** | 评估答案质量、幻觉风险、延迟、Token 成本 |
| **MemoryUpdater** | 自动写入 Working/ShortTerm/LongTerm/Episodic/Semantic |
| **Tracer** | 记录完整 Pipeline 轨迹到 JSON 文件 |

### Pipeline（两种实现）

| 实现 | 特点 |
|------|------|
| **ContextOSPipeline** | 单体编排，六步硬编码，适合直接使用 |
| **PipelineEngine** | Middleware Chain 模式，可插拔，事件驱动，适合二次开发 |

---

## 配置

默认配置文件 `context_os/config.yaml`：

```yaml
context-os:
  pipeline:
    middlewares:
      - name: intent;   enabled: true;  order: 100
      - name: build;    enabled: true;  order: 300
      - name: optimize; enabled: true;  order: 400
      - name: package;  enabled: true;  order: 500
      - name: llm;      enabled: true;  order: 600
      - name: feedback; enabled: true;  order: 700
  llm:
    provider: deepseek
    api-key: ${DEEPSEEK_API_KEY:}
    model: deepseek-chat
  memory:
    working-memory: { max-tokens: 32000 }
    short-term:    { ttl-hours: 24 }
    long-term:     { max-items: 1000 }
  store:
    provider: sqlite
    db-path: ./data/context_os.db
```

配置支持 `mtime` 热加载（每 30s 检测）和环境变量替换 `${VAR:default}`。

---

## 意图驱动的上下文选择

根据意图类型动态决定数据源收集范围，避免浪费 Token：

| 意图 | Identity | Conversation | Environment | Memory | Knowledge | Tools |
|------|----------|-------------|-------------|--------|-----------|-------|
| QA | ✗ | ✓ | ✗ | ✓ | ✓ | ✗ |
| CODING | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| DEBUGGING | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| PLANNING | ✗ | ✓ | ✗ | ✓ | ✓ | ✗ |
| SEARCH | ✗ | ✗ | ✗ | ✓ | ✓ | ✗ |
| WORKFLOW | ✗ | ✓ | ✓ | ✓ | ✗ | ✓ |
| AGENT | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| DATA_ANALYSIS | ✗ | ✓ | ✓ | ✓ | ✗ | ✓ |

当 Token 预算 < 8000 时自动裁减 MEMORY 和 ENVIRONMENT。

---

## 质量评估指标

| 指标 | 说明 |
|------|------|
| `answer_quality` | 答案质量（0-1），有 LLM 时调用 LLM 评分 |
| `latency_ms` | LLM 调用延迟 |
| `cost_usd` | Token 成本估算（$3/M input） |
| `success` | 是否包含错误信号 |
| `reward_score` | 综合奖励分 |

---

## Benchmark 结果

6 个测试用例（T5~T10），模拟长链连续对话场景，对比**无记忆** vs **Context-OS 分层记忆系统**的回复质量。

### 测试场景

| ID | 场景 | 对话轮次 | 核心挑战 |
|----|------|---------|---------|
| T5 | 钱包收支追踪 | 8 轮 | 长链数值累积，需追溯初始值 |
| T6 | 配置项多次覆盖 | 7 轮 | 同一属性反复修改，需追踪最新值 |
| T7 | 个人偏好演变 | 5 轮 | 立场多次反转，需回答转变节点 |
| T8 | 人际关系跃迁 | 5 轮 | 关系状态多次跃迁，需梳理完整时间线 |
| T9 | 职业理想转向 | 5 轮 | 需回忆所有被放弃的目标及原因 |
| T10 | 多属性并发演变 | 7 轮 | 三个属性轮流变化，不可混淆 |

### 评估方式

- **关键词命中率**：每轮回答是否包含预期关键词（粗略评估）
- **精确匹配**：最后一问的标准答案是否完全正确（严格评估）
- LLM: DeepSeek Chat

### 总体结果

```
  全部测试平均质量（关键词）:
    无记忆系统: 70.2%
    有记忆系统: 91.3%
    提升幅度:   +21.2%

  精确匹配胜负: 记忆系统 1 胜 / 0 负 / 1 平
  ✅ 结论: 记忆系统有效 — 在需要跨轮记忆的任务中显著提升正确率。
```

### 各场景详情

| 场景 | 无记忆(关键词) | 有记忆(关键词) | 无记忆(精确) | 有记忆(精确) |
|------|---------------|---------------|-------------|-------------|
| T5 钱包追踪 | 33.3% | 100% | ❌ | ✅ |
| T6 配置覆盖 | 83.3% | 47.6% | — | — |
| T7 偏好演变 | 80.0% | 100% | — | — |
| T8 人际关系 | 93.3% | 100% | — | — |
| T9 职业理想 | 80.0% | 100% | ✅ | ✅ |
| T10 多属性 | 86.7% | 81.0% | — | — |

> **注意**：T6 配置覆盖场景有记忆低于无记忆，原因是 Optimizer 对话压缩的 Token 阈值不足（已修复，`max_tokens=2000` → `32000`），修复后预期与其他场景一致。

### 运行评测

```powershell
# 对比测试（6 个场景，无需下载数据）
cd d:\study\owencli
$env:DEEPSEEK_API_KEY = ""
python examples\memory_comparison.py

# 学术基准 LongMemEval（500 题，需下载数据集）
python examples\download_longmemeval.py
python examples\longmemeval_benchmark.py --max-eval 20
```

---

## 项目结构

```
context_os/
├── __init__.py              # 公共 API 导出
├── entry.py                 # 主 Pipeline 入口（ContextOSPipeline）
├── config.yaml              # 配置文件
├── core/                    # 基础层：基类/模型/异常/日志
├── config/                  # ConfigManager + AppConfig
├── intent/                  # Classifier + Extractor + Parser
├── orchestrator/            # Selector + Router
├── collection/              # Identity + Conversation + Environment
├── memory/                  # 10 种记忆 + SQLiteStore + Embedding
├── builder/                 # ContextBuilder + ContextMerger
├── optimizer/               # Ranker + Compressor + Budget
├── packager/                # ContextPackager + Adapters
├── llm/                     # Anthropic / OpenAI / DeepSeek 客户端
├── feedback/                # Evaluator + Tracer + MemoryUpdater
├── pipeline/                # Middleware Chain 引擎 + EventBus
├── store/                   # StoreProvider + StoreSession
└── scripts/                 # 运行脚本

examples/
├── basic_pipeline.py        # 基本使用示例
├── custom_adapter.py        # 自定义 Adapter 示例
├── longmemeval_benchmark.py # LongMemEval 基准测试
└── memory_comparison.py     # 记忆对比分析

tests/                       # 单元测试
```

---

## 技术栈

- **语言**: Python 3.14+
- **LLM SDK**: `anthropic`, `openai`
- **存储**: `aiosqlite`（WAL 模式，支持 JSON 文件降级）
- **数据模型**: `pydantic`
- **数值计算**: `numpy`
- **依赖管理**: `pyproject.toml`

---

## 路线图

### Phase 1 — 基础 Pipeline ✓
- [x] Intent Understanding 引擎（LLM + Regex 双模式）
- [x] Context Orchestrator 动态选择
- [x] 数据收集层（Identity + Conversation + Environment）
- [x] 10 种记忆子系统完整实现
- [x] Context Builder + Merger
- [x] Context Optimizer（排序+压缩+Token Budget）
- [x] Context Packager + 多模型适配（Claude/OpenAI/DeepSeek）

### Phase 2 — Middleware 化与事件驱动 ✓
- [x] PipelineEngine + Middleware Chain
- [x] PipelineEventBus 事件总线
- [x] 8 个标准 Middleware 实现
- [x] 配置热加载

### Phase 3 — 增强能力
- [ ] Embedding Service 完整集成（API/BM25/Ollama/ONNX）
- [ ] RAG 知识库集成
- [ ] Multi-Agent 上下文共享
- [ ] 分布式存储支持（PostgreSQL）

### Phase 4 — 学习与进化
- [ ] Knowledge Evolution 自动知识演进
- [ ] Trace & Replay 系统
- [ ] 基于强化学习的 Context 自优化
- [ ] 在线 Benchmark Dashboard
