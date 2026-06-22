# Context-OS Memory System — 测试用例

> 用于验证记忆系统的 10 层存储、Fact Extraction、Importance Scoring、跨 session 检索。

---

## 目录

1. [基础事实提取](#1-基础事实提取)
2. [事实更新与版本化](#2-事实更新与版本化)
3. [重要性评分验证](#3-重要性评分验证)
4. [复杂长对话](#4-复杂长对话)
5. [跨 session 记忆检索](#5-跨-session-记忆检索)
6. [混合引擎（规则→LLM 降级）](#6-混合引擎规则llm-降级)
7. [语义相似度去重](#7-语义相似度去重)
8. [分层存储策略验证](#8-分层存储策略验证)
9. [边界情况](#9-边界情况)

---

## 1. 基础事实提取

### 1.1 规则引擎命中 —— 姓名

| 输入 | 期望命中规则 | 期望 FactMemory |
|------|------------|----------------|
| `我叫张三` | `name_default` | `user.name = 张三` |
| `以后叫我李四` | `name_later` | `user.name → 李四` (UPDATE) |
| `我改名叫王五` | `name_renamed` | `user.name → 王五` (UPDATE, history=[张三,李四,王五]) |
| `请叫我赵六` | `name_callme` | `user.name → 赵六` |

**验证点：** 输入第 2、3、4 条后，`/memory` 查看 Fact Memory 应只显示 `user.name = 赵六`，history 保留全部变更记录。

### 1.2 规则引擎命中 —— 语言/技能

| 输入 | 期望 FactMemory |
|------|----------------|
| `我主要写 Go` | `user.preferred_language = Go` |
| `我喜欢用 Rust` | `user.preferred_language = Rust` (UPDATE) |
| `我擅长 Kubernetes` | `user.preferred_language = Kubernetes` (注意：规则会误匹配) |

### 1.3 规则引擎命中 —— 职业/位置

| 输入 | 期望 FactMemory |
|------|----------------|
| `我是后端工程师` | `user.occupation = 后端工程师` |
| `我就职于字节跳动` | `user.occupation → 字节跳动` (UPDATE) |
| `我住在北京` | `user.location = 北京` |

### 1.4 规则引擎命中 —— 平台

| 输入 | 期望 FactMemory |
|------|----------------|
| `我主要用 Kubernetes 开发` | `user.preferred_platform = Kubernetes` |

---

## 2. 事实更新与版本化

### 2.1 同一属性多次变更

```
User: 我叫张三
  → Fact: user.name = 张三 (history=[])

User: 以后叫我李四
  → Fact: user.name = 李四 (history=[张三])

User: 改名叫王五
  → Fact: user.name = 王五 (history=[张三, 李四])

User: 我的名字是什么？
  → 检索 Fact: user.name = 王五
  → Agent: "你的名字是王五"
```

**验证点：** `/memory` 显示 `user.name = 王五`。不应该出现「你有三个名字：张三、李四、王五」。

### 2.2 冲突检测：低置信度不应覆盖高置信度

```
User: 我叫张三
  → rule 命中, confidence=0.95

User: 我可能叫李四吧
  → 规则未命中 → LLM 提取
  → LLM 返回 confidence=0.60
  → ConflictChecker: 0.60 < 0.95 → REJECTED_LOW_CONFIDENCE
  → FactMemory 不变: user.name = 张三
```

**验证点：** 第二次后 `/memory` 仍显示 `user.name = 张三`。

---

## 3. 重要性评分验证

### 3.1 各维度评分预期

| 输入 | Rule | Semantic | Novelty | FactWt | Goal | Final | 存储层 |
|------|:----:|:--------:|:-------:|:------:|:----:|:-----:|:------:|
| `你好` | 0.20 | 0.05 | 0.80 | 0.05 | 0.50 | **0.25** | SHORT_TERM |
| `谢谢` | 0.20 | 0.05 | 0.80 | 0.05 | 0.50 | **0.25** | SHORT_TERM |
| `我叫张三` | 0.35 | 0.90 | 1.00 | 1.00 | 0.50 | **0.79** | EPISODE_LTM |
| `我喜欢 Rust` | 0.35 | 0.85 | 1.00 | 0.90 | 0.50 | **0.76** | EPISODE_LTM |
| `帮我写一个 Dockerfile` | 0.55 | 0.70 | 0.80 | 0.70 | 0.30 | **0.62** | CONVERSATION_MED |
| `Kubernetes pod CrashLoopBackOff 怎么排查` | 0.60 | 0.85 | 1.00 | 0.60 | 0.30 | **0.72** | CONVERSATION_MED |
| `我公司叫字节跳动，做云计算平台` | 0.35 | 0.95 | 1.00 | 0.95 | 0.50 | **0.80** | EPISODE_LTM |
| `今天天气不错` | 0.20 | 0.10 | 0.60 | 0.20 | 0.50 | **0.26** | SHORT_TERM |

### 3.2 长文本评分

```
用户: 我是一个有 10 年经验的后端工程师，主要使用 Go 和 Rust，最近在研究
Kubernetes 和云原生技术栈。我在字节跳动基础架构团队工作，负责设计高可用
分布式系统。之前曾在阿里巴巴中间件团队任职，主导了消息队列的架构升级。
```

| 维度 | 预期 | 原因 |
|:----:|:----:|------|
| Rule | 0.85 | 成功+长度>100+多实体+技术关键词 |
| Semantic | 0.95 | LLM 判定：10 年后这些信息仍然重要 |
| Novelty | 1.00 | 首次出现 |
| FactWeight | 0.95 | 身份+职业+公司+技能 |
| Goal | 0.50 | 无历史任务 |
| **Final** | **0.84** | **→ EPISODE_LTM** |

### 3.3 第二次重复输入（验证 Novelty 降权）

```
User: 我叫张三 (第一次)
  → Novelty = 1.00

User: 我叫张三 (第二次，完全一样)
  → NoveltyScorer: embedding cosine > 0.95
  → Novelty = 0.05
  → Final = 0.20×0.35 + 0.35×0.90 + 0.20×0.05 + 0.15×1.00 + 0.10×0.50
          = 0.07 + 0.315 + 0.01 + 0.15 + 0.05 = 0.595
          → CONVERSATION_MED（降级）
```

**验证点：** 第二次不会被写入 LTM。

---

## 4. 复杂长对话

### 4.1 完整开发场景

```
System: Context-OS Agent 已启动

User: 你好
  → Rule=0.20, Novelty=0.80, FactWt=0.05, Final≈0.25
  → SHORT_TERM (24h)

User: 我叫张三，是一名后端工程师
  → 规则命中: name_default + occupation_role
  → Fact: user.name = 张三
  → Fact: user.occupation = 后端工程师
  → Final≈0.79 → EPISODE_LTM

User: 我主要用 Go 和 Kubernetes
  → 规则命中: language_default + platform_dev
  → Fact: user.preferred_language = Go (UPDATE 如果之前有)
  → Fact: user.preferred_platform = Kubernetes
  → Final≈0.76 → EPISODE_LTM

User: 帮我写一个 Kubernetes Deployment，用 Go 写一个健康检查接口
  → Rule=0.55(+code), Semantic=0.80, FactWt=0.70, Goal=0.60
  → Final≈0.66 → CONVERSATION_MED (7天)
  → 同时触发 GoalRelationScorer: "Kubernetes" + "Go" 匹配之前 Facts
  → 存入 TaskGraph

User: 刚才的 pod CrashLoopBackOff 了，怎么排查？
  → Rule=0.60(+error), Semantic=0.85, Goal=0.75(+匹配 TaskGraph)
  → Final≈0.75 → EPISODE_LTM
  → 因为是 Debug 意图 → RetrievalPlanner 侧重 Episode+Reflection

User: 以后叫我李四
  → 规则命中: name_later
  → Fact: user.name → 李四 (UPDATE, history=[张三])
  → Final≈0.79 → EPISODE_LTM

User: 我的名字是什么？
  → ContextBuilder: 检索 FactMemory
  → 返回: user.name = 李四
  → Agent: "你的名字现在是李四，之前曾用名张三"
```

**验证点：**
1. Fact Memory 应只显示 `user.name = 李四`，而不是两条
2. TaskGraph 应记录 "Kubernetes Deployment" 任务
3. `pod CrashLoopBackOff` 的 GoalRelation 应高于 0.70（匹配之前 Kubernetes）

### 4.2 企业级对话

```
User: 我在阿里巴巴云原生团队工作了 5 年，主要负责 K8s 集群管理平台的开发。
我们团队维护了 3000+ 个节点，每天处理百万级别的 Pod 调度。最近在做
Cluster API 相关的项目，用 Go 写了大量的 Operator。
  → 规则命中: occupation + platform + language
  → Fact: user.occupation = 云原生团队
  → Fact: user.preferred_platform = Kubernetes
  → Fact: user.preferred_language = Go
  → Rule=0.85, Semantic=0.95, Novelty=1.00, FactWt=0.95
  → Final≈0.87 → EPISODE_LTM

User: 我现在的项目遇到了一个 etcd 的性能问题，3000 节点的心跳导致
etcd 的写入压力太大了，有什么优化建议？
  → Rule=0.55(+长度+技术), Semantic=0.90, Goal=0.80(匹配"集群管理")
  → FactWt=0.80(tool)
  → Final≈0.74 → CONVERSATION_MED

User: 以后叫我老王吧
  → 规则命中: name_callme
  → Fact: user.name → 老王 (UPDATE)
  → Final≈0.79 → EPISODE_LTM

User: 刚才说的 etcd 优化，我试了调整 --heartbeat-interval，效果不明显
  → GoalRelation: 匹配 TaskGraph 中 "etcd 性能问题"
  → GoalRelation = 0.85
  → Final: 规则长度+技术+目标关联 → 约 0.73 → CONVERSATION_MED
```

**验证点：**
1. Fact Memory 应累积 4 条事实
2. 第二次关于 etcd 的提问应关联到之前的 "etcd 性能问题" 任务
3. 跨对话上下文（任务关联）应体现在 step 6 的 GoalRelation 分数中

---

## 5. 跨 Session 记忆检索

### 5.1 基础跨 session

```
=== Session 1 (第一次运行) ===
User: 我叫张三
User: 我主要用 Kubernetes

=== 关闭应用，重新启动 ===

=== Session 2 (第二次运行，新 sessionId) ===
User: 我的名字是什么？
  → ContextBuilder: FactMemory.retrieve("名字")
  → 返回: user.name = 张三
  → Agent: "你的名字是张三"

User: 我擅长什么平台？
  → ContextBuilder: FactMemory.retrieve("平台") OR LTM.retrieve("擅长")
  → 返回: user.preferred_platform = Kubernetes
  → Agent: "你主要用 Kubernetes"

User: 你好（验证 Conversation 不跨 session）
  → ConversationMemory.retrieve: sessionId ≠ 新 session
  → 返回空
```

**验证点：**
1. Fact 和 LTM 数据可跨 session 检索
2. Conversation Memory 按 sessionId 隔离，新 session 看不到旧对话

### 5.2 冲突合并跨 session

```
=== Session 1 ===
User: 我叫张三

=== Session 2 ===
User: 以后叫我李四
  → ConflictChecker: 找到 user.name = 张三
  → candidate.value(李四) ≠ existing.value(张三)
  → UPDATE
  → Fact: user.name = 李四 (history=[张三])

=== Session 3 ===
User: 我的名字是什么？
  → Agent: "你的名字是李四"
  → 不会提及张三
```

---

## 6. 混合引擎（规则→LLM 降级）

### 6.1 规则命中（快速路径）

| 输入 | 路径 | 耗时 |
|------|------|:----:|
| `我叫张三` | Rule → Validator → ConflictChecker → FactUpdater | **<1ms** |
| `以后叫我李四` | Rule → Validator → ConflictChecker → FactUpdater | **<1ms** |

### 6.2 规则未命中 → LLM 降级

| 输入 | 规则结果 | LLM 预期输出 |
|------|---------|-------------|
| `其实同事都叫我老王` | 未命中 | `[{"type":"user.nickname","value":"老王","confidence":0.85}]` |
| `大家都喊我 Tony` | 未命中 | `[{"type":"user.nickname","value":"Tony","confidence":0.85}]` |
| `我平时写代码喜欢用 VS Code` | 未命中 | `[{"type":"user.preferred_editor","value":"VS Code","confidence":0.80}]` |
| `我现在有点累` | 未命中 | `[]` (临时状态，不应存储) |
| `帮我查一下天气预报` | 未命中 | `[]` (任务请求，不是事实) |

**验证点：**
1. `其实同事都叫我老王` → FactMemory 应有 `user.nickname = 老王`
2. `我现在有点累` → FactMemory 不变，无新增
3. LLM 提取的任务请求应被 Validator 过滤

---

## 7. 语义相似度去重

### 7.1 完全重复

```
User: 我叫张三
User: 我叫张三  (第二次)
  → NoveltyScorer: cosine > 0.95
  → Novelty = 0.05
  → 最终不存入 LTM
```

### 7.2 语义等价但表述不同

```
User: 我是后端工程师
  → Fact: user.occupation = 后端工程师

User: 我做后端开发
  → NoveltyScorer: 现有 fact "后端工程师" vs 新输入 "后端开发"
  → cosine ≈ 0.82 (高度相似)
  → Novelty = 1.0 - 0.82 = 0.18 → 打折后 0.09
  → Final: 受 Novelty 拖累，不升 LTM
```

### 7.3 完全不同

```
User: 我叫张三
  → Fact: user.name = 张三

User: 我喜欢吃火锅  (10 分钟后)
  → NoveltyScorer: "张三" vs "火锅" → cosine ≈ 0.10
  → Novelty = 0.90
  → 正常评分，不受影响
```

---

## 8. 分层存储策略验证

### 8.1 各层级边界值

| 输入 | 期望 Final | 期望存储层 | 验证方法 |
|------|:---------:|:---------:|---------|
| `我叫张三，在字节跳动工作，主要用 Go 和 K8s，有 5 年经验` | ≥ 0.90 | **FACT_SEMANTIC** | `/memory` 查看 LTM 应有条目 |
| `帮我优化一下这个 SQL 查询，它跑得太慢了` | 0.50~0.74 | **CONVERSATION_MED** | 7 天后自动清理 |
| `嗯` | < 0.20 | **DISCARD** | 不应出现在任何记忆中 |
| `好的` | < 0.20 | **DISCARD** | 不应出现在任何记忆中 |
| `今天周二` | 0.20~0.49 | **SHORT_TERM** | 24h 后自动过期 |

### 8.2 问候语不应污染 LTM

```
User: 你好
  → Final ≈ 0.25 → SHORT_TERM
User: 早上好
  → Final ≈ 0.25 → SHORT_TERM
User: 谢谢
  → Final ≈ 0.25 → SHORT_TERM
User: 再见
  → Final ≈ 0.25 → SHORT_TERM

验证: /memory 查看 LTM，应无问候条目
```

---

## 9. 边界情况

### 9.1 空输入

```
User: (空字符串)
  → 应忽略，不处理
```

### 9.2 纯标点/表情符号

```
User: 。。。
User: 😊😊😊
  → Rule=0.20(仅成功), FactWt≈0.05
  → Final≈0.25 → SHORT_TERM (24h 后自动过期)
```

### 9.3 超长输入 (5000+ 字)

```
User: (粘贴一篇文章)
  → Rule=0.45(成功+>100+多实体)
  → Semantic: LLM 可能会给中等分数
  → FactWeight: 可能不匹配任何事实类型
  → Final≈0.50~0.60 → CONVERSATION_MED
  → 不会升级到 LTM（因为没有重要事实）
```

### 9.4 名字中带罕见字符

```
User: 我叫张𪚥
  → 正则: [\u4e00-\u9fff\w]{1,20}
  → 𪚥 属于扩展B区(CJK Ext B)，不在 \u4e00-\u9fff 范围内
  → 规则可能无法匹配 → 降级到 LLM
```

### 9.5 多语言混合

```
User: My name is Zhang San, 我主要用 Go and Kubernetes
  → 规则: "我叫" 不匹配, "主要用" 匹配
  → 部分命中: language_default → Go
  → 姓名未命中 → LLM 降级
```

---

## 运行测试

```bash
# 进入项目目录
cd java-context-os

# 启动交互式 Agent
mvn compile exec:java -Dexec.mainClass="com.owencli.contextos.agent.InteractiveAgent"

# 或者直接运行
mvn package -DskipTests
java -jar target/context-os-0.1.0.jar
```

在 Agent 中输入上述用例，观察 `/memory` 和 Step 6 的评分输出来验证。
