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

5 类记忆层 + 独立知识系统，分层设计见 [完整架构文档](docs/MEMORY_ARCHITECTURE.md)：

| 记忆层 | 回答的问题 | 存储 | 生命周期 |
|--------|-----------|------|---------|
| **Working** | "我现在在干什么？" | 纯内存 Ring Buffer，容量 8000 tokens | 当前 session，FIFO 淘汰 |
| **Session** | "这次对话发生了什么？" | SQLite `memories` (type="session")，TTL 24h | 单次 session |
| **LongTerm** | "我对用户/项目了解什么？" | SQLite `memories` (type="long_term")，Fact + Summary | 跨 session |
| **Experience** | "我以前做过什么？学到了什么？" | SQLite `experiences` (多标签 tags JSON 数组) | 跨 session |
| **+Knowledge** | "概念之间怎么关联？" | SQLite `concepts` + `concept_relations`（知识图谱） | 跨 session，不衰减 |

**写入流程**：Pipeline 执行完成 → Journal.append()（写前日志） → EventBus 分发 → Write Decision 三层门控：

```
Layer 1（规则必存）: 显式记忆指令、KV 键值对、任务关键结论 → 直接通过
Layer 2（新颖度）  : embedding cosine > 0.9 → 实体值对比 → 更新或丢弃
Layer 3（重要性）  : 5 维加权评分（Identity 0.30 + State 0.20 + Task 0.20 + Cold Start 0.15 + Quality 0.15）
                  → 阈值 ≥ 0.50 通过 → Memory Router 分流
```

**检索流程**：UnifiedRetriever（5 个 SourceAdapter）→ 跨源统一 6 维评分 + source_weight → 排序截断：

```
score = 0.30 × semantic + 0.20 × bm25 + 0.15 × source_reliability
      + 0.10 × time_decay + 0.15 × relevance_boost + 0.10 × access_frequency
final = score × source_weight (LTM=1.0 > Experience=0.8 > Knowledge=0.6 > Journal=0.4 > Session=0.3)
```

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

最新测试时间：2026-07-10，模型：DeepSeek，整体评分 **88.5% (B+)**。

### 测试场景

| ID | 场景 | 核心挑战 |
|----|------|---------|
| T1 | 多用户金融管理 | 跨用户追踪收入/支出/冲正/利息，多实体推理 |
| T2 | 多层配置级联 | 全局→项目→用户三级配置继承与覆盖关系 |
| T3 | 社交关系网络 | 多角色关系链（认识/合作/怀疑/和解等）动态演变 |
| T4 | 系统监控时序 | CPU/内存/磁盘/TPS 多指标持续变化趋势分析 |
| T5 | 钱包余额推理 | 长链数值累积，需从反向问题追溯初始余额 |
| T6 | 跨会话记忆干扰 | Session B 需正确引用 Session A 的完整配置链 |

### 评估方式

三层加权评估：

```
final_score = 0.30 × keyword_recall + 0.40 × llm_judge + 0.30 × structured_compare
```

- **Keyword Recall（30%）**：预期关键词是否出现在回复中
- **LLM Judge（40%）**：LLM 根据 ground truth 评分（0-10）
- **Structured Compare（30%）**：JSON 字段级精确匹配

### 记忆 Benchmark（6 用例）

| Case | SimpleAgent | MemoryAgent | Δ 提升 | Pass |
|------|:-----------:|:-----------:|:------:|:----:|
| T1 金融多用户 | 0% | **68%** | +68% | ✅ |
| T2 配置级联 | 36% | **100%** | +64% | ✅ |
| T3 社交网络 | 4% | **60%** | +56% | ✅ |
| T4 系统监控 | 24% | **73%** | +49% | ✅ |
| T5 钱包推理 | 8% | **70%** | +62% | ✅ |
| T6 跨会话 | 56% | **100%** | +44% | ✅ |

**汇总：**

| 指标 | 数值 |
|------|:----:|
| MemoryAgent 平均准确率 | **78.6%** |
| SimpleAgent 平均准确率 | 21.3% |
| 记忆系统提升幅度 | **+57.3%** |
| 用例通过率 | **6/6 (100%)** |

### Scoring Dashboard

| 维度 | 得分 | 说明 |
|------|:---:|------|
| intent | 100.0% | 意图识别准确率 |
| collection | 100.0% | 上下文数据收集 |
| builder | 100.0% | 上下文构建 |
| **memory** | **78.6%** | 记忆系统准确率 |
| recall | 100.0% | 记忆检索召回率 |
| compression | 76.0% | 上下文压缩效率 |
| feedback | 100.0% | 反馈闭环 |
| reflection | 100.0% | 自我反思 |
| pipeline | 52.7% | 全链路延迟评分 |
| **Overall** | **88.5% (B+)** | |

### 关键结论

- 记忆系统在所有 6 个测试用例上显著优于无记忆基线，平均提升 **+57.3%**
- 所有模块测试通过率 **100%**
- pipeline 延迟评分 52.7%，仍有优化空间
- 详细架构说明见 [docs/MEMORY_ARCHITECTURE.md](docs/MEMORY_ARCHITECTURE.md)

### 运行评测

```powershell
# 完整 Benchmark（所有测试）
cd d:\study\owencli
$env:DEEPSEEK_API_KEY = ""
python -m benchmark.run --mode all
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
├── memory/                  # 5 层记忆系统 + SQLiteStore + Embedding
├── builder/                 # ContextBuilder + ContextMerger
├── optimizer/               # Ranker + Compressor + Budget
├── packager/                # ContextPackager + Adapters (Claude/OpenAI/DeepSeek)
├── llm/                     # Anthropic / OpenAI / DeepSeek 客户端
├── feedback/                # Evaluator + Tracer + MemoryUpdater
├── pipeline/                # Middleware Chain 引擎 + EventBus
└── scripts/                 # 运行脚本

benchmark/                   # 基准测试框架
├── run.py                   # 入口
├── benchmark_runner.py      # 7 种测试类型
├── evaluator.py             # 三层评估引擎
├── metrics.py               # 指标聚合
├── reporter.py              # HTML/JSON/Console 报告
├── agents.py                # SimpleAgent vs MemoryAgent
├── observer.py              # Pipeline 执行观察器
├── assertions.py            # 模块断言
├── datasets/                # 6 个记忆用例 + 5 个意图用例
└── reports/                 # 生成的测试报告

docs/
├── MEMORY_ARCHITECTURE.md   # 记忆系统架构文档
└── ...

examples/
├── basic_pipeline.py        # 基本使用示例
└── ...

java-context-os/             # Java 生产部署版本（Spring Boot + Maven）
├── behavior/                # 行为模式学习
├── runtime/                 # Agent 运行时状态管理
├── importances/             # 6 维度记忆重要性评分器
├── feedback/extraction/     # LLM/Rule 事实提取引擎
└── ...

tests/                       # 单元测试（294 个）
```

> 完整技术文档见 [docs/MEMORY_ARCHITECTURE.md](docs/MEMORY_ARCHITECTURE.md) — 涵盖写入流程、检索排序、设计原则、存储表设计等。

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
