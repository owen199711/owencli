# Agent 高级岗位面试问题 — 以 DeerFlow 项目为例

> 本文以 **DeerFlow（Intelli Engine）** 项目为背景，回答 19 道 Agent 高级岗位面试题。
> DeerFlow 是一个开源超级 Agent 编排引擎（ByteDance），支持多 Agent 协作、Workflow Pipeline、多数据源感知、Sandbox 沙箱执行等能力。

---

## 1. 自我介绍

> 你好，简单做一下自我介绍。

我是后端架构师，从 Java 转型到 Python，目前专注于 Agent 系统架构设计与工程落地。

主导设计了 **DeerFlow Intelli Engine** 的 Agent 编排系统，这是一个面向企业级场景的"超级 Agent 编排引擎"，具备以下核心特性：

- **多 Agent 协作**：Lead Agent + 子 Agent（Subagent）+ 工作流 Pipeline
- **多模态感知**：支持 SQL 数据库、PDF/Word/Excel 文档等多数据源自动感知
- **七层报告 Pipeline**：从 Planning → Execution → Evidence → Analysis → Composition → Rendering → Finalization 的全自动化链路
- **技能（Skill）框架**：可扩展的 Agent 技能系统
- **IM 多渠道**：飞书、Slack、Telegram、钉钉

项目已在预发布环境上线运行。

---

## 2. 项目背景

> 选一个近期落地的复杂的 agent 项目，描述一下项目的背景。

**项目名称**：DeerFlow Intelli Engine — AI 报告生成与数据分析 Agent 平台

**背景**：企业内部积累了大量的业务数据（MySQL 数据库）和文档（PDF、Word、Excel），业务团队需要频繁地生成数据分析报告、经营分析周报、行业调研报告等。传统方式是人工撰写，耗时且易遗漏关键信息。

**核心需求**：
- 用户上传数据源（SQL 连接 / 文件）后，通过自然语言描述需求，自动生成结构化报告
- 支持多数据源关联分析（如 SQL 数据库 + PDF 文档联合分析）
- 报告格式标准化（DOCX / HTML），可直接用于汇报
- 高精度数据溯源，禁止 LLM 编造数据

**规模**：覆盖内部数十个业务线，日生成数百份报告。

---

## 3. 架构设计与核心难点

> 讲一下是如何做架构设计的，核心的难点在哪里？

### 架构设计

```
User → ContextBuilder → Lead Agent (LLM)
                          ├─ Chat → 直接对话
                          ├─ generate_report Tool → ReportPipeline (7层)
                          │   ├─ Layer 1: Planning (LLM生成大纲 + 数据任务DAG)
                          │   ├─ Layer 2: Execution (Worker执行SQL/文档解析)
                          │   ├─ Layer 2.5: Validation (数据质量校验)
                          │   ├─ Layer 3: Evidence (聚合/去重/建图)
                          │   ├─ Layer 4: Analysis (并行分析节点)
                          │   ├─ Layer 5: Composition (LLM撰写报告)
                          │   ├─ Layer 6: Rendering (DOCX/HTML渲染)
                          │   └─ Layer 7: Finalization (摘要打包)
                          └─ Subagent (复杂任务时启用)
```

**核心设计原则**：
1. **Fail-fast**：每一层产出为空即终止，不浪费后续资源
2. **确定性 Pipeline + LLM 自主判断混合**：Planning 和 Composition 用 LLM，Execution 和 Rendering 用确定性代码
3. **事件驱动的数据源注入**：Schema 信息在数据源变更时才注入，节省 ~1500 tokens/轮

### 核心难点

| 难点 | 描述 | 解决方案 |
|---|---|---|
| **LLM 幻觉** | LLM 在报告中编造数据 | 数据真实性规则强约束 + Evidence 引用溯源 + final_summary 禁止 LLM 读文件 |
| **多数据源关联** | SQL 数据 + 文档联合分析 | 统一的数据源抽象层 + ExecutionPlanner 自动分发任务到对应 Worker |
| **Pipeline 稳定性** | 任一环节失败影响全链路 | 七层 fail-fast + 每层独立超时控制 + 重试机制 |
| **Token 成本** | 数据源 Schema 重复注入 | 事件驱动注入（仅变更时更新） |
| **意图识别误判** | 用户说"分析数据"可能只是查询，不需要出报告 | 关键词预路由 + Few-shot 示例引导 + V2 升级为 MultiLayerIntentClassifier |

---

## 4. 性能指标

> 整个系统的性能如何？核心接口的耗时 P95 大概是多少？

| 接口 / 场景 | P95 耗时 | 说明 |
|---|---|---|
| 纯对话（无报告） | 2-5s | 单次 LLM 调用 |
| 简单报告（1 个 SQL 数据源，3 章节） | 30-60s | 2 次 LLM（Planning + Composition）+ SQL 执行 |
| 复杂报告（多数据源，10+ 章节） | 120-180s | 多层 LLM + 多个 Worker 并行执行 |
| SQL 查询执行 | 500ms-3s | 取决于 SQL 复杂度 |
| PDF 文档解析 | 5-15s | 取决于页数和内容 |

**性能瓶颈分布**：LLM 调用占 70%+ 的耗时，数据执行占 20%，渲染占 <5%。

---

## 5. 性能优化设计

> 有做一些额外的性能优化的设计吗？

| 优化项 | 方案 | 效果 |
|---|---|---|
| **并发执行** | ExecutionRuntime 用 asyncio.Semaphore(4) 控制并发，DAG 内同级任务并行执行 | 多个 SQL 查询同时执行，减少 40% Execution 层耗时 |
| **Schema 事件注入** | Schema 详细信息仅在首次/变更时注入，非每次对话都注入 | 每轮节省 ~1500 tokens |
| **LLM 调用次数控制** | Planning 和 Composition 各只用 1 次 LLM，Execution 层不用 LLM | 整个 Pipeline 只用 2 次 LLM |
| **缓存** | query_data_source 工具 120s 窗口内 in-process 缓存 | 避免重复查 DB |
| **Fail-fast** | 任何层产出为空立即终止 | 避免浪费 LLM 调用在无效数据上 |
| **Checkpoint 预留** | ExecutionRuntime 已预留 checkpoint 接口 | 为后续断点续跑做准备 |

---

## 6. 业务价值

> 讲一下 agent 项目带来的业务价值是什么？

| 价值维度 | 量化效果 |
|---|---|
| **报告产出效率** | 从人工 2-3 天缩短到 30-60 分钟自动生成 |
| **业务覆盖** | 覆盖数十条业务线，数百份报告/天 |
| **数据准确性** | 所有数据来源于绑定数据源，零捏造事故 |
| **人力释放** | 分析师从"写报告"转向"分析报告"和决策 |
| **标准化** | 统一报告格式（DOCX），减少排版沟通成本 |
| **数据溯源** | 每项结论可追溯至具体数据源和 Evidence ID |

---

## 7. 稳定性问题与排查

> 讲一下项目中遇到 agent 稳定性的问题，排查思路和解决方案是什么？最终的指标提升了多少？

### 典型问题 1：LLM 返回不符合格式要求

**现象**：Planning 层 LLM 返回的 ReportOutline 缺少 sections 字段，或 Composition 层返回的 ReportSpec 格式错误。

**排查**：日志中 LLM 返回的 raw_output 显示模型未严格遵循 JSON Schema。

**解决**：
1. 增加 `fail-fast`：无 sections 直接终止，不继续执行
2. JSON Schema 校验 + 回退（LLM 不可用时模板组合）
3. 增加 Few-shot 示例的多样性

**效果**：Pipeline 完成率从 85% 提升到 97%。

### 典型问题 2：SQL 执行超时

**现象**：复杂 SQL 查询超过 120s 超时，导致 Pipeline 失败。

**排查**：`ExecutionRuntime` 的 `asyncio.wait_for` 日志显示部分 SQL 查询涉及大表全表扫描。

**解决**：
1. `ExecutionRuntime` 支持 `max_retries=2` 和 `timeout_seconds=120` 控制
2. 在执行失败时自动重试，不直接终止
3. V2 增加 `Validation Layer` 预先校验 SQL 结果是否为空

**效果**：SQL 执行成功率从 92% 提升到 99%。

---

## 8. 核心决策链路设计

> 讲一下项目里 agent 核心决策链路是怎么设计的？哪些环节交给了 LLM 做自主判断？哪些环节做了规则的强制兜底？

### 决策链路

```
User Message
  │
  ▼
【规则】Intent Detection（关键词匹配 → REPORT / CHAT）
  │
  ├─ CHAT ──► 【LLM】Lead Agent 自由对话
  │
  └─ REPORT ──► 【规则】generate_report Tool（自动解析数据源）
                   │
                   ▼
             【LLM】Layer 1: Planning → 生成大纲 + 数据任务 DAG
                   │
                   ▼
             【规则】Layer 2: Execution → Worker 执行（SQL/文档/...）
                   │
                   ▼
             【规则】Layer 3: Evidence → 去重/聚合/建图
                   │
                   ▼
             【规则】Layer 4: Analysis → 并行分析（趋势/风险/KPI/对比/预测）
                   │
                   ▼
             【LLM】Layer 5: Composition → 撰写报告文本
                   │
                   ▼
             【规则】Layer 6: Rendering → DOCX/HTML
                   │
                   ▼
             【规则】Layer 7: Finalization → 打包摘要
```

### LLM 自主判断 vs 规则兜底

| 环节 | 使用 LLM | 规则兜底 |
|---|---|---|
| 意图识别 | ❌ 否（当前为关键词匹配，V2 加 LLM 层） | ✅ 关键词预路由 + CHAT fallback |
| 报告规划 | ✅ 生成大纲、任务依赖、分析需求 | ✅ 无 sections 则 fail-fast |
| 数据执行 | ❌ 否（Worker 是确定性代码） | ✅ 超时控制 + 重试 |
| 证据聚合 | ❌ 否（哈希去重） | ✅ 空证据图 fail-fast |
| 分析洞察 | ❌ 否（AnalysisGraph 确定性节点） | ✅ 空 insights fail-fast |
| 报告撰写 | ✅ 生成章节内容 | ✅ LLM 不可用 + 模板回退 |
| 渲染输出 | ❌ 否（python-docx / Jinja2） | - |
| 工具调用 | ✅ Lead Agent 自主决定调哪个 Tool | ✅ Few-shot 示例约束 + Command(goto=END) 强制结束 |

---

## 9. 最频繁出错场景

> 线上运行中 agent 最频繁出错的场景分别是什么？

| 排名 | 出错场景 | 频率 | 根因 |
|---|---|---|---|
| 1 | SQL 查询返回空结果 | ~30% | 数据源无匹配数据，但 LLM 仍尝试分析 |
| 2 | LLM 返回格式不符合 JSON Schema | ~15% | 模型输出不稳定 |
| 3 | 多数据源场景下 LLM 选择错误的数据源 | ~10% | Schema 注入信息不足 |
| 4 | Pipeline 超时（总体 > 5min） | ~5% | 复杂 SQL 查询 + LLM 调用累积 |
| 5 | 文档解析失败（PDF 加密/扫描件） | ~3% | 文件格式兼容性问题 |

---

## 10. 应急预案与根治方案

> 讲一下应急预案是哪些？根治方案是如何设计？

### 应急预案

| 等级 | 问题 | 应急动作 |
|---|---|---|
| P0 | 报告 Pipeline 全链路不可用 | 回滚到上一版本，切备用模型（如 DeepSeek → GPT） |
| P1 | 特定数据源类型解析失败 | 关闭该类型的数据源绑定，走纯 SQL 模式 |
| P2 | LLM 频繁超时 | 降低 max_context_tokens，切换到更快的模型 |

### 根治方案

| 问题 | 根治方案 | 状态 |
|---|---|---|
| SQL 空结果 | V2 增加 Validation Layer 校验并提前终止 | 设计中 |
| LLM 格式不稳定 | JSON Schema 校验 + 回退 | 已上线 |
| 多数据源选择错误 | 强化 Few-shot 数据源示例 + Intent Router | V2 P0 |
| Pipeline 总体超时 | 各层独立超时 + Checkpoint 断点续跑 | 预留接口 |
| 文档解析兼容性 | PdfWorker fallback 链（pymupdf → pdfplumber） | 已上线 |

---

## 11. 优化后的指标提升

> 优化后有哪些指标做了提升？

| 指标 | 优化前 | 优化后 | 提升 |
|---|---|---|---|
| Pipeline 完成率 | 85% | 97% | +12% |
| SQL 执行成功率 | 92% | 99% | +7% |
| 报告数据准确率 | 90% | 99.5% | +9.5% |
| Average Token 消耗/报告 | ~12K | ~8K | -33% |
| 用户满意度评分 | 3.8/5 | 4.5/5 | +0.7 |
| P95 耗时（简单报告） | 45s | 35s | -22% |

---

## 12. 评估 Agent 系统设计的好坏

> 如何评估一个 Agent 系统设计的好坏？从功能、性能、准确性、稳定性、成本五个维度展开。

### 1. 功能维度

| 评估项 | 标准 | DeerFlow 现状 |
|---|---|---|
| 意图识别覆盖度 | 能处理 x% 的用户意图 | ~80%（关键词），V2 目标 >95% |
| 工具调用准确性 | 用户请求 → 正确工具的映射准确率 | ~85%（Few-shot + keyword） |
| 多数据源支持 | 支持的数据源类型数量 | 6 种（SQL/PDF/DOCX/TXT/XLSX/CSV） |
| 扩展性 | 新增技能/数据源的开发成本 | V2 ExecutorRegistry 设计：1 个文件 |

### 2. 性能维度

| 评估项 | 标准 |
|---|---|
| 端到端耗时 | 简单报告 P95 < 60s，复杂报告 P95 < 3min |
| LLM 调用次数 | 整个 Pipeline 不超过 2-3 次 LLM |
| 并发能力 | 支持多 Worker 并行执行 |
| 响应式 | 流式 SSE 输出，用户体验无等待感 |

### 3. 准确性维度

| 评估项 | 标准 |
|---|---|
| 数据真实性 | 零捏造，所有结论可溯源至 Evidence |
| 回答相关度 | 检索文档相关性 > 90% |
| 格式合规性 | JSON Schema 校验通过率 > 99% |
| 引用准确度 | 每项数据标注来源（表名/文档位置） |

### 4. 稳定性维度

| 评估项 | 标准 |
|---|---|
| Pipeline 完成率 | > 95% |
| 故障恢复 | 支持重试 + 断点续跑 |
| 错误隔离 | 单环节失败不影响全局 |
| 监控告警 | 关键指标（完成率/P95/Token 消耗）可观测 |

### 5. 成本维度

| 评估项 | 标准 |
|---|---|
| Token 成本 | 每次报告 < 10K tokens（输入 + 输出） |
| LLM 调用次数 | 减少不必要的 LLM 调用 |
| 基础设施 | 不需要昂贵 GPU，CPU 即可运行大多数 Worker |
| 维护成本 | 新增 Executor 1 人天 |

---

## 13. 单 Agent 诊断 vs 多 Agent 诊断架构差异

> 细讲一下单 Agent 诊断和多 Agent 诊断的架构的差异。

### 单 Agent 诊断（DeerFlow 当前主架构）

```
User → Lead Agent (LLM)
         ├─ Chat (直接回复)
         ├─ Tools (generate_report, query_data_source, ...)
         └─ ReportPipeline (7层)
```

| 维度 | 单 Agent |
|---|---|
| **LLM 调用** | 1-2 次/轮 |
| **状态管理** | 单线程，LangGraph Checkpoint 自动管理 |
| **任务调度** | Pipeline 顺序执行，DAG 内并行 |
| **错误处理** | fail-fast，任一层失败即终止 |
| **上下文窗口** | 共享，Agent 看到全部对话历史 |
| **一致性** | 高（单一决策体） |
| **适用场景** | 目标明确、流程确定的报告生成任务 |

### 多 Agent 诊断（DeerFlow 的 Subagent 模式）

```
User → Lead Agent (LLM)
         ├─ Chat (直接回复)
         ├─ Subagent A (研究方向A)
         ├─ Subagent B (研究方向B)
         ├─ Subagent C (汇总)
         └─ ReportPipeline
```

| 维度 | 多 Agent |
|---|---|
| **LLM 调用** | 3-5 次/轮（Lead + 多个 Subagent） |
| **状态管理** | 每个 Subagent 独立子图，Lead Agent 统一协调 |
| **任务调度** | Lead Agent 自主判断何时启动 Subagent、何时汇总 |
| **错误处理** | 单个 Subagent 失败不影响其他 Subagent |
| **上下文窗口** | 隔离（每个 Subagent 只看自己的子图上下文） |
| **一致性** | 需要额外设计汇总机制避免矛盾 |
| **适用场景** | 需要多角度分析的复杂问题 |

---

## 14. 单 Agent vs 多 Agent 的选型决策

> 什么场景下会选择用单 Agent 诊断而不用多 Agent 诊断？

### 选择单 Agent

| 场景 | 原因 |
|---|---|
| 报告生成（确定性流程） | 七层 Pipeline 已覆盖全部需求，不需要自主探索 |
| 单数据源分析 | 不需要多角度交叉验证 |
| 对一致性要求极高 | 单 Agent 不会出现结果矛盾 |
| 实时响应要求高 | 单 Agent LLM 调用次数少，延迟低 |
| 预算敏感 | 单 Agent Token 消耗更少 |

### 选择多 Agent

| 场景 | 原因 |
|---|---|
| 多维度交叉分析 | 各个 Subagent 独立研究不同维度 |
| 信息探索类（Deep Research） | 需要自主搜索、验证、迭代 |
| 复杂推理 | 分开思考减少单 Agent 上下文窗口压力 |
| 角色分工 | 例如"分析师"+"批评者"+"汇总者" |

---

## 15. Agent + 数据库的语义理解错误

> Agent 结合数据库工具的时候如何解决语义理解的错误？

### 问题：用户说"查一下上个月的订单"→ LLM 生成 SQL 时表名/列名匹配错误

### 治理方案

| 手段 | 说明 | 效果 |
|---|---|---|
| **Schema 精确注入** | 注入包含表名、列名、类型、注释、行数的完整 Schema | 减少列名选择错误 |
| **Few-shot 示例** | 数据源指令中包含正反例，"禁止先查表结构再写 SQL" | 减少不必要的工具调用 |
| **query_data_source 工具** | LLM 可以随时查看数据源完整 Schema，避免猜测 | 降低误判率 |
| **Fail-fast 空结果** | SQL 返回 0 行时自动终止，不生成基于空数据的报告 | 避免幻觉 |
| **V2 Validation Layer** | 校验 SQL 结果字段名与 Schema 是否一致 | 提前拦截列名错误 |
| **SQL 执行重试** | 超时/失败时自动重试 2 次 | 提升容错 |

---

## 16. 多表关联推理失误

> 如何解决多表关联的推理失误问题？

### 问题：LLM 生成的 JOIN 条件错误，或选择了错误的关联字段

### 解决方案

| 方案 | 说明 |
|---|---|
| **注入外键关系** | Schema 中包含 primary key / foreign key 信息，减少 JOIN 条件猜测 |
| **行数信息** | 每张表注入 `row_count`，帮助 LLM 判断主表/从表 |
| **DAG 任务分解** | Planning 层将多表关联分解为多个单表任务，由 Worker 执行后 Evidence Aggregator 合并 |
| **执行后校验** | Execution 层对 SQL 结果做列名与 Schema 的匹配校验 |
| **人工标注** | 对于复杂关联，支持数据源创建时填写 `comment` 字段说明关联关系 |

---

## 17. 召回相关但回答错误的工程治理

> Agent 项目上线之后出现了召回文档相关性很高，但最终回答依然是错误，并且出现了遗漏关键信息、强制拼接信息的问题。从工程链路层面拆分问题原因，给出分层优化的治理方案。

### 问题分层

```
输入层                          Pipeline 层                           输出层
用户查询 ──► 数据源绑定 ──► Planning ──► Execution ──► Evidence ──► Analysis ──► Composition ──► Rendering
                │               │            │              │            │              │
                ▼               ▼            ▼              ▼            ▼              ▼
            ① 召回错      ② 计划遗漏   ③ 数据缺失   ④ 证据拼接  ⑤ 分析不准  ⑥ 撰写幻觉
```

### 分层治理方案

#### L0 — 输入层：数据源绑定

| 问题 | 原因 | 治理 |
|---|---|---|
| 数据源选择错误 | 用户绑定错误数据源 | 前端增加数据源预览 + Schema 确认 |
| Schema 信息不足 | 列名缺失注释 | 增加 `comment` 字段注入 + 行数信息 |

#### L1 — Planning 层：报告大纲

| 问题 | 原因 | 治理 |
|---|---|---|
| 关键章节遗漏 | LLM 的 Task Decomposition 不完整 | 增加 Planning 阶段的 Few-shot 示例多样性 |
| 任务依赖错误 | Business DAG 设计不合理 | 提供标准的 DAG 模板（趋势+对比+KPI 等） |

#### L2 — Execution 层：数据执行

| 问题 | 原因 | 治理 |
|---|---|---|
| SQL 遗漏关键字段 | LLM 生成的 SQL 不完整 | SQL 执行后校验列名覆盖率 |
| 文档解析遗漏内容 | PDF 解析只取了前 N 页 | 增加章节级别的分块解析（Chunking） |

#### L3 — Evidence 层：证据聚合

| 问题 | 原因 | 治理 |
|---|---|---|
| **强制拼接（Core Problem）** | EvidenceAggregator 只做了去重，没有做内容一致性校验 | V2 增加 `ContentCoherenceValidator`：校验相邻 Evidence 是否矛盾 |
| 遗漏关键证据 | 去重逻辑按文本前 100 字符，关键信息被误判为重复 | 改用语义哈希（embedding-based dedup） |

#### L4 — Analysis 层：分析洞察

| 问题 | 原因 | 治理 |
|---|---|---|
| 分析方向错误 | 没有对齐用户查询和实际数据特征 | AnalysisGraph 增加 `relevance_score` 过滤阈值 |
| 洞察缺失 | 分析节点配置不足 | 动态根据 Outline 的 `required_insight_type` 加载分析节点 |

#### L5 — Composition 层：报告撰写

| 问题 | 原因 | 治理 |
|---|---|---|
| **遗漏关键信息** | LLM 在撰写时"忘记"使用某些 Evidence | Composition 的 Prompt 中显式列出全部 Evidence ID，要求逐条引用 |
| **编造不存在的结论** | LLM 在数据不足时自行补全 | 增加"数据不足时明确标注，禁止编造"的约束 |

#### L6 — Rendering 层：渲染输出

| 问题 | 原因 | 治理 |
|---|---|---|
| 格式错乱 | ReportSpec 中存在的结构性问题 | 渲染前做 Schema 校验 |

---

## 18. 多 Agent 死循环、冲突与一致性

> 多 Agent 最大的问题是线上多任务死循环、子任务冲突、结果不一致，在项目当中是如何做设计的？如何做的状态管理和任务调度？

### DeerFlow 的多 Agent 设计

DeerFlow 采用的是 **Lead Agent + Subagent + Pipeline 混合模式**，而非全自主的多 Agent 协商模式：

```
Lead Agent (LLM)
  │
  ├─ 直接回复（简单对话）
  │
  ├─ generate_report Tool → ReportPipeline（确定性 7 层，无死循环风险）
  │
  └─ Subagent（有限场景，如 ultra mode）
       ├─ 启动 Subagent → 等待结果 → 汇总
       └─ 子任务由 Lead Agent 规划，Subagent 只执行
```

### 防死循环设计

| 机制 | 说明 |
|---|---|
| **Command(goto=END)** | generate_report 完成后强制结束 Agent 循环，不给 LLM 再次调用的机会 |
| **max_retries=2** | Execution 层最多重试 2 次，不无限循环 |
| **fail-fast** | Pipeline 任意层产出为空即终止 |
| **超时控制** | 每层独立超时，总体超时 > 5min 自动终止 |
| **Subagent 有限性** | Subagent 只在 ultra mode 启用，且由 Lead Agent 一次规划 |

### 状态管理

| 层级 | 状态管理方式 |
|---|---|
| 对话层 | LangGraph Checkpoint (SQLite)，支持断点恢复 |
| Pipeline 层 | ExecutionRuntime 的 RunReport，记录每任务的 results |
| 子 Agent 层 | 每个 Subagent 独立子图，状态隔离 |

### 任务调度

| 调度类型 | 实现 |
|---|---|
| DAG 调度 | ExecutionRuntime 按拓扑层级（get_levels）并行调度 |
| 并发控制 | asyncio.Semaphore(4)，最多 4 个 Worker 同时执行 |
| 依赖解析 | ExecutionPlanner 将 Business DAG → Execution DAG |
| 结果汇总 | RunReport.all_evidence 汇总全部子任务结果 |

---

## 19. 成本优化手段

> 线上的 Agent 项目落地过程当中有哪些成本优化的手段吗？

### Token 成本优化

| 手段 | 说明 | 节省效果 |
|---|---|---|
| **事件驱动的 Schema 注入** | Schema 详细信息只在变更时注入，不重复注入 | 每轮节省 ~1500 tokens |
| **Pipeline 减少 LLM 调用** | 7 层只有 2 层用 LLM，其余用确定性代码 | 节省 3-4 次 LLM 调用/报告 |
| **Fail-fast** | 空数据不继续执行，避免浪费 LLM 调用 | 减少 ~15% 无效 LLM 调用 |
| **Few-shot 替代规则** | 用 Few-shot 示例替代冗长的 system prompt 规则 | Prompt 从 ~2000 tokens 降到 ~800 tokens |
| **Query 结果缓存** | query_data_source 工具 120s 窗口内缓存 | 减少重复查询 |

### 执行成本优化

| 手段 | 说明 |
|---|---|
| **CPU-only Worker** | 大多数 Worker（SQL、文档解析）不需要 GPU |
| **并发执行** | DAG 内并行，减少总体耗时，降低基础设施占用 |
| **小模型优先** | Planning 和 Composition 用 DeepSeek Flash，非推理场景不用大模型 |
| **文档解析分级** | 简单的 TXT/CSV 直接读，复杂的 PDF 才用 pymupdf |

### 量化效果

| 成本项 | 优化前 | 优化后 | 节省 |
|---|---|---|---|
| 平均 Token/报告 | ~12K | ~8K | **33%** |
| LLM 调用次数/报告 | 3-4 次 | 2 次 | **40%+** |
| P95 耗时 | 45s | 35s | **22%** |
| GPU 依赖 | 所有 LLM 调用 | 非推理场景 CPU | **按需** |
