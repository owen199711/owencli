# Context-OS Java 版架构优化计划

> 参考 Intelli Engine (DeerFlow) 架构，对 java-context-os 进行系统性优化

---

## 一、优化目标总览

| 维度 | 当前状态 | 目标状态 | DeerFlow 参考 |
|---|---|---|---|
| 架构分层 | 单模块 Maven | 双模块：core + spring-boot-starter | App → Harness 两层分离 |
| 配置系统 | Spring pplication.yml，无热加载 | YAML 分层配置 + mtime 热加载 | AppConfig + ExtensionsConfig |
| Pipeline 编排 | 嵌套 CompletableFuture 硬编码 | **Middleware Chain** 可插拔可排序 | 17 个 AgentMiddleware |
| 事件机制 | 无 | PipelineEventBus 统一事件 | StreamBridge + EventStore |
| 存储抽象 | SQLite 硬编码 | StoreProvider SPI：SQLite/PG/H2 | Checkpointer 多后端 |
| 测试覆盖 | 零自动化测试 | 分层测试：UT + 集成测试 | ~200 pytest fixtures |

---

## 二、模块拆分

## 三、五大核心优化

### 3.1 Middleware Chain

将 ContextOSPipeline.java 的硬编码阶段重构为可插拔 Middleware：

**内置中间件（按 order 排序）**：
| Order | Middleware | 职责 |
|---|---|---|
| 100 | IntentMiddleware | TaskParser + IntentClassifier |
| 200 | PolicyMiddleware | ContextPolicy.evaluate(task) |
| 300 | BuildMiddleware | ContextBuilder + ContextMerger |
| 400 | OptimizeMiddleware | Ranker + Compressor + BudgetAllocator |
| 500 | PackageMiddleware | ContextPackager + Adapter |
| 600 | LLMMiddleware | LLMClient.complete() |
| 700 | FeedbackMiddleware | QualityEvaluator + MemoryUpdater |
| 800 | ReflectMiddleware | ReflectionEngine |
| 900 | ConsolidateMiddleware | MemoryLifecycle + KnowledgeEvolution |

**收益**：用户可自定义 Middleware 插入任意位置、运行时启用/禁用、调整排序

### 3.2 PipelineEventBus

统一事件机制，支持监控、Metrics、SSE 流式推送。

**内置消费者**：TraceEventHandler / MetricsEventHandler / SSEBridge

### 3.3 StoreProvider SPI

StoreProvider 接口 + SQLite / PostgreSQL / H2 多实现，配置可切换。

### 3.4 分层配置 + 热加载

config.yaml 独立于 Spring，ConfigManager 每 30s 检测 mtime 自动重载。

### 3.5 测试体系

JUnit 5 + @ExtendWith Extension，覆盖 Pipeline / Memory / Feedback / Store / LLM / Intent / Optimizer。

---

## 四、实施路线图

### Phase 1：模块拆分 + 存储 SPI（1-2 周）
1.1 父 POM + 模块目录创建
1.2 StoreProvider SPI + SQLite 适配抽取
1.3 H2Store（测试用内存存储）
1.4 MemoryManager → SPI 解耦

### Phase 2：Middleware Chain + EventBus（1-2 周）
2.1 PipelineMiddleware + PipelineEngine 核心编排
2.2 现有 8 阶段 → 8 个 Middleware
2.3 PipelineEventBus 事件类型 + 注册/分发
2.4 Trace 重写为 EventBus 消费者

### Phase 3：配置 + 测试（2-3 周）
3.1 AppConfig YAML 模型 + SnakeYAML 解析
3.2 ConfigManager + mtime 热加载
3.3 Starter 自动配置：pplication.yml → AppConfig
3.4 8 组测试类 + JUnit5 Extension

---

## 五、兼容性策略

| 变更 | 兼容策略 |
|---|---|
| Pipeline | 旧 ContextOSPipeline 标记 @Deprecated，新 PipelineEngine 并行 |
| 配置 | 旧 pplication.yml 自动检测并告警迁移 |
| 数据库 | SQLiteStore 自动检测旧表结构原地迁移 |
| API | MemoryManager 接口签名不变，内部切换到 SPI |
