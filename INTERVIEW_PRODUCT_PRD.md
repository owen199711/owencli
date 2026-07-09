# AI 面试助手 — 产品需求文档（PRD）

> 基于记忆系统的智能面试训练平台，核心差异化在于 **"记住你的每一次面试"**

---

## 一、产品定位

### 1.1 产品名称

**AI 面试助手**（AI Interview Coach）

### 1.2 核心价值主张

> "AI 记住你的每一次面试，持续追踪弱点，量身定制提升路径"

传统面试模拟产品只关注单次练习，本产品通过**记忆系统**记住用户的：
- 每次面试表现（情景记忆）
- 长期能力变化（长期记忆）
- 知识掌握程度（语义记忆/知识图谱）
- 当前面试状态（工作记忆/短期记忆）

从而实现**自适应出题、个性化反馈、持续进步追踪**。

### 1.3 目标用户

| 用户群体 | 核心需求 |
|---|---|
| **应届毕业生** | 积累面试经验，了解岗位要求，快速提升技术能力 |
| **在职开发者** | 查漏补缺，针对性强化薄弱环节，准备跳槽面试 |
| **技术管理者** | 模拟晋升面试，提升技术深度和管理能力 |

### 1.4 竞品差异化

| 维度 | 传统产品 | AI 面试助手（本产品） |
|---|---|---|
| 记忆能力 | 无，每次面试独立 | 5 层记忆系统，持续追踪用户状态 |
| 出题方式 | 随机或固定题库 | 基于记忆和能力画像自适应出题 |
| 反馈深度 | 简单对错判断 | 多维度分析 + 历史对比 + 改进建议 |
| 知识积累 | 被动学习 | 主动构建个人知识图谱 |
| Skill 系统 | 无 | 按岗位/行业分类的技能包，用户可安装使用 |

---

## 二、核心功能模块

### 2.1 模块架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户层                                      │
│   主对话入口    │   Skill 技能中心   │   成果中心   │   个人中心    │
├─────────────────┼───────────────────┼─────────────┼──────────────┤
│   面试模拟      │   Skill 浏览/搜索  │   报告下载  │   能力画像   │
│   实时状态输出  │   按标签过滤       │   历史记录  │   学习计划   │
│   技能选择      │   安装/卸载        │   收藏管理  │   偏好设置   │
├─────────────────────────────────────────────────────────────────────┤
│                         业务层                                      │
│   对话管理      │   Skill 管理       │   成果管理   │   用户管理    │
│   状态追踪      │   技能匹配        │   报告生成   │   记忆管理   │
├─────────────────────────────────────────────────────────────────────┤
│                         AI 引擎层                                   │
│                    ┌─────────────────────┐                         │
│                    │    Context-OS       │                         │
│                    │    Memory Pipeline  │                         │
│                    │  Working/STM/LTM/   │                         │
│                    │  Episodic/Semantic  │                         │
│                    └──────────┬──────────┘                         │
│                               │                                     │
│                    ┌──────────▼──────────┐                         │
│                    │     LLM 推理引擎    │                         │
│                    │   (通义千问/GPT)     │                         │
│                    └─────────────────────┘                         │
├─────────────────────────────────────────────────────────────────────┤
│                         数据层                                      │
│   PostgreSQL    │   ChromaDB      │   Redis        │   MinIO       │
│   (结构化数据)   │   (向量检索)     │   (会话缓存)    │   (文件存储)   │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 2.2 模块一：主对话（面试模拟）

**参考风格**：`http://172.16.0.71:8088/AITalk` 的状态输出风格 + Workbuddy 的 Skill 添加方式

#### 2.2.1 功能描述

用户进入对话界面，可选择或不选择 Skill 进行面试模拟：
- **选择 Skill**：使用该 Skill 的专属题库、Prompt 模板和评估维度
- **不选择 Skill**：AI 根据用户输入自动匹配已安装的 Skill

#### 2.2.2 状态输出

实时展示面试进度和状态：

```
┌─────────────────────────────────────────────────────────────────┐
│  面试状态: 第 3/10 题    |    得分: 72/100    |    预计剩余: 8min │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  技术能力   │  │  表达能力   │  │  逻辑能力   │              │
│  │    75%      │  │    68%      │  │    78%      │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│                                                                 │
│  [用户] 请介绍一下你对微服务的理解                                │
│                                                                 │
│  [AI] 好的，这是一个架构设计类问题。请从以下几个方面展开：         │
│       1. 微服务的核心概念                                        │
│       2. 与单体架构的对比                                        │
│       3. 你在项目中的实际应用                                    │
│                                                                 │
│  [用户] 微服务是...（用户输入）                                   │
│                                                                 │
│  [AI] 📊 评估反馈：                                             │
│       ✓ 概念理解准确（+15分）                                    │
│       ✓ 对比分析清晰（+12分）                                    │
│       ✗ 缺少实际案例（-5分）                                     │
│                                                                 │
│  [建议] 下次回答时加入具体项目经历，说明你在微服务改造中           │
│         遇到的挑战和解决方案。                                    │
│                                                                 │
│  [技能] 当前使用: 后端架构师面试技能                              │
│                                                                 │
│  [操作] [选择技能] [结束面试] [保存成果]                          │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.2.3 Skill 选择机制

```
用户输入 → AI 意图识别 → 匹配用户已安装的 Skill
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
        精准匹配        模糊匹配        无匹配
            │               │               │
            ▼               ▼               ▼
       使用该Skill     询问用户确认    使用默认通用模式
```

#### 2.2.4 数据模型

```sql
-- 面试会话表
CREATE TABLE interview_session (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL,
    skill_id        VARCHAR(36),           -- 选中的 Skill（可选）
    status          VARCHAR(20) NOT NULL,  -- pending/ongoing/finished
    current_question INT DEFAULT 0,
    total_questions  INT DEFAULT 10,
    score           INT DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 面试轮次表
CREATE TABLE interview_turn (
    id              VARCHAR(36) PRIMARY KEY,
    session_id      VARCHAR(36) NOT NULL,
    question        TEXT NOT NULL,         -- AI 提问
    user_answer     TEXT,                  -- 用户回答
    ai_feedback     TEXT,                  -- AI 反馈
    score           INT,                   -- 本轮得分
    evaluation_dimensions JSONB,           -- 多维度评估
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

### 2.3 模块二：Skill 技能中心

#### 2.3.1 功能描述

统一的技能市场，用户可以：
- 浏览所有可用 Skill
- 按行业/岗位标签过滤
- 安装/卸载 Skill
- 查看 Skill 详情

#### 2.3.2 Skill 分类体系

```
Skill 技能中心
    │
    ├── 按行业分类
    │       ├── 互联网
    │       ├── 金融
    │       ├── 医疗
    │       │       ├── 糖尿病专科面试
    │       │       ├── 心血管内科面试
    │       │       └── ...
    │       ├── 教育
    │       └── ...
    │
    ├── 按岗位分类
    │       ├── 后端开发
    │       │       ├── Java 工程师面试
    │       │       ├── Go 工程师面试
    │       │       └── Python 工程师面试
    │       ├── 前端开发
    │       ├── 算法工程师
    │       ├── 产品经理
    │       └── ...
    │
    └── 按技能类型
            ├── 技术面试
            ├── 行为面试
            ├── 系统设计
            └── 英语口语
```

#### 2.3.3 Skill 详情页

```
┌─────────────────────────────────────────────────────────────────┐
│  Java 后端工程师面试技能                                          │
│                                                                 │
│  ⭐⭐⭐⭐⭐ (4.8分)    |    已安装: 12,580人                        │
│                                                                 │
│  [标签] 后端开发 | Java | SpringBoot | MySQL | 微服务            │
│                                                                 │
│  【技能介绍】                                                     │
│  专为 Java 后端工程师设计的面试技能包，涵盖：                      │
│  • 基础语法与数据结构                                             │
│  • SpringBoot 框架原理                                           │
│  • 数据库设计与优化                                               │
│  • 分布式系统设计                                                 │
│  • 微服务架构实践                                                 │
│                                                                 │
│  【评估维度】                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  技术深度   │  │  代码质量   │  │  架构能力   │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│                                                                 │
│  【关联知识库】                                                   │
│  • Java 核心技术文档                                              │
│  • Spring Framework 源码分析                                       │
│  • MySQL 性能优化指南                                              │
│                                                                 │
│  [操作] [卸载技能] [开始面试]                                     │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.3.4 数据模型

```sql
-- Skill 技能表
CREATE TABLE skill (
    id              VARCHAR(36) PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    industry_tags   TEXT[],                -- 行业标签
    position_tags   TEXT[],                -- 岗位标签
    icon_url        VARCHAR(255),
    rating          DECIMAL(2,1) DEFAULT 0,
    install_count   INT DEFAULT 0,
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 用户安装的 Skill
CREATE TABLE user_skill (
    user_id         VARCHAR(36) NOT NULL,
    skill_id        VARCHAR(36) NOT NULL,
    installed_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMP,
    PRIMARY KEY (user_id, skill_id)
);

-- Skill 关联知识库
CREATE TABLE skill_knowledge (
    skill_id        VARCHAR(36) NOT NULL,
    knowledge_id    VARCHAR(36) NOT NULL,
    weight          DECIMAL(3,2) DEFAULT 1.0,
    PRIMARY KEY (skill_id, knowledge_id)
);

-- Skill Prompt 模板
CREATE TABLE skill_prompt (
    id              VARCHAR(36) PRIMARY KEY,
    skill_id        VARCHAR(36) NOT NULL,
    type            VARCHAR(20) NOT NULL,  -- question/feedback/evaluation
    template        TEXT NOT NULL,
    version         VARCHAR(20) DEFAULT '1.0'
);
```

---

### 2.4 模块三：数据源 + Skill 关联

#### 2.4.1 功能描述

用户添加数据源（文档、代码、笔记等）时，可以选择关联到已安装的 Skill：

```
┌─────────────────────────────────────────────────────────────────┐
│                    添加数据源                                     │
│                                                                 │
│  【上传文件】                                                     │
│  ┌─────────────────────────────────────┐                        │
│  │  拖拽文件到此处，或点击选择文件        │                        │
│  └─────────────────────────────────────┘                        │
│                                                                 │
│  【选择关联 Skill】                                               │
│  以下是你已安装的 Skill，选择关联后该数据                          │
│  将成为 Skill 的知识库：                                          │
│                                                                 │
│  ☐ Java 后端工程师面试技能                                        │
│  ☐ 系统设计面试技能                                               │
│  ☐ MySQL 数据库技能                                               │
│                                                                 │
│  [下一步] [取消]                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.4.2 数据模型

```sql
-- 用户数据源
CREATE TABLE user_data_source (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL,
    name            VARCHAR(200) NOT NULL,
    file_path       VARCHAR(500),
    content_type    VARCHAR(100),
    size            BIGINT,
    status          VARCHAR(20) NOT NULL,  -- uploading/processing/ready/failed
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 数据源与 Skill 关联
CREATE TABLE data_source_skill (
    data_source_id  VARCHAR(36) NOT NULL,
    skill_id        VARCHAR(36) NOT NULL,
    PRIMARY KEY (data_source_id, skill_id)
);

-- 数据切片（用于向量检索）
CREATE TABLE data_chunk (
    id              VARCHAR(36) PRIMARY KEY,
    data_source_id  VARCHAR(36) NOT NULL,
    content         TEXT NOT NULL,
    embedding       REAL[],
    metadata        JSONB,
    chunk_index     INT
);
```

---

### 2.5 模块四：成果中心

#### 2.5.1 功能描述

用户可以：
- 查看历史面试记录
- 下载面试报告（PDF/Word）
- 保存成果到个人空间
- 查看能力变化趋势

#### 2.5.2 面试报告示例

```
┌─────────────────────────────────────────────────────────────────┐
│                    AI 面试助手 — 面试报告                          │
│                                                                 │
│  面试日期: 2026-07-05    |    时长: 35分钟                       │
│  使用技能: Java 后端工程师面试技能                                │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                      能力雷达图                              │  │
│  │                                                           │  │
│  │     ┌─────────────────────────────────────────────┐        │  │
│  │     │  技术深度     表达能力     逻辑能力         │        │  │
│  │     │      ●────────●────────●                    │        │  │
│  │     │    ╱│        │        │                    │        │  │
│  │     │   ╱ │        │        │                    │        │  │
│  │     │  ╱  │        │        │                    │        │  │
│  │     │ ╱   │        │        │                    │        │  │
│  │     │●────●────────●────────●                    │        │  │
│  │     │ 代码质量     架构能力     问题解决           │        │  │
│  │     └─────────────────────────────────────────────┘        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  【面试记录】                                                     │
│  1. 微服务理解           得分: 75/100     评级: B                │
│     优点: 概念清晰，对比分析到位                                 │
│     改进: 缺少实际项目案例                                       │
│                                                                 │
│  2. SpringBoot 原理      得分: 82/100     评级: A                │
│     优点: IoC/DI 理解深入                                       │
│     改进: 可进一步讲解自动配置原理                               │
│                                                                 │
│  3. MySQL 优化           得分: 65/100     评级: C                │
│     优点: 索引优化思路正确                                       │
│     改进: 缺少对查询优化器的理解                                 │
│                                                                 │
│  【改进建议】                                                     │
│  1. MySQL 查询优化器原理                                        │
│  2. 准备 2-3 个微服务项目案例                                     │
│  3. SpringBoot 自动配置源码分析                                  │
│                                                                 │
│  【推荐学习资源】                                                 │
│  • 《MySQL 技术内幕》第 7 章                                     │
│  • Spring Framework 官方文档                                     │
│  • 系统设计面试题解析                                             │
│                                                                 │
│  [下载 PDF] [下载 Word] [保存到成果]                              │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.5.3 数据模型

```sql
-- 用户成果表
CREATE TABLE user_achievement (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL,
    type            VARCHAR(20) NOT NULL,  -- interview_report/skill_certificate
    title           VARCHAR(200) NOT NULL,
    description     TEXT,
    file_url        VARCHAR(500),
    is_favorite     BOOLEAN DEFAULT false,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

## 三、记忆系统映射（面试场景）

### 3.1 5 层记忆 → 面试场景映射

| 记忆层 | 面试场景映射 | 存储内容 | 生命周期 |
|---|---|---|---|
| **Working** | 当前面试轮次 | 当前问题、用户回答、AI 反馈、实时得分 | 面试会话中 |
| **Short-Term** | 单次面试会话 | 完整面试记录、各题得分、评估维度 | 面试结束后 24h |
| **Long-Term** | 用户能力画像 | 长期得分趋势、知识掌握程度、弱点标签 | 持久 |
| **Episodic** | 历次面试经历 | 场景（岗位）、行动（回答）、结果（得分）、反馈 | 持久 |
| **Semantic** | 岗位知识图谱 | 概念（如"微服务"）、关系（如"微服务→SpringCloud"） | 持久 |

### 3.2 记忆更新流程

```
用户完成一次面试
    │
    ├─ WorkingMemory 更新
    │     └── 记录当前轮次的问题、回答、反馈
    │
    ├─ ShortTermMemory 更新
    │     └── 记录完整面试会话（用于本轮复盘）
    │
    ├─ LongTermMemory 更新（评分 >= 阈值）
    │     └── 更新用户能力画像、知识掌握程度
    │
    ├─ EpisodicMemory 更新
    │     └── 记录"场景-行动-结果-反馈"链
    │
    └─ SemanticMemory 更新
          └── 从面试中提取新概念、更新概念关系
```

### 3.3 记忆驱动的自适应出题

```
用户开始面试
    │
    ├─ 检索 LongTermMemory → 获取用户能力画像
    │     └── 识别薄弱环节（如"MySQL 优化"掌握度 40%）
    │
    ├─ 检索 EpisodicMemory → 获取历史面试经历
    │     └── 避免重复出题，发现常见错误模式
    │
    ├─ 检索 SemanticMemory → 获取岗位知识图谱
    │     └── 确定知识点关联（如"微服务"→"SpringCloud"→"服务发现"）
    │
    └─ AI 生成问题
          └── 优先针对薄弱环节，兼顾知识体系完整性
```

---

## 四、用户旅程

### 4.1 新用户旅程

```
注册/登录 → 完善个人信息（岗位、目标公司）
              │
              ▼
         浏览 Skill 技能中心
              │
              ▼
         安装感兴趣的 Skill（如"Java 后端工程师"）
              │
              ▼
         添加个人数据源（简历、项目经验、笔记）
              │
              ▼
         开始面试模拟（选择或不选择 Skill）
              │
              ▼
         AI 自适应出题 → 用户回答 → AI 实时反馈
              │
              ▼
         面试结束 → 生成报告 → 保存成果
              │
              ▼
         查看能力变化 → 获取改进建议 → 制定学习计划
              │
              ▼
         继续练习（针对薄弱环节）
```

### 4.2 老用户旅程

```
登录 → 查看个人能力画像（变化趋势）
         │
         ├─ 选择上次未完成的面试
         │     │
         │     ▼
         │  继续面试 → 完成 → 生成报告
         │
         ├─ 查看历史面试记录
         │     │
         │     ▼
         │  对比分析 → 发现进步 → 获取新建议
         │
         └─ 安装新 Skill / 添加新数据源
               │
               ▼
              开始新的面试练习
```

---

## 五、技术架构

### 5.1 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端层                                    │
│   Vue3 + TypeScript + Element Plus                              │
│   组件：对话组件、技能卡片、报告展示、图表组件                      │
├─────────────────────────────────────────────────────────────────┤
│                        网关层                                    │
│   Spring Cloud Gateway                                          │
│   功能：路由转发、认证鉴权、限流熔断                              │
├─────────────────────────────────────────────────────────────────┤
│                        服务层                                    │
│   ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
│   │ 用户服务       │  │ Skill 服务     │  │ 面试服务       │   │
│   │ UserService    │  │ SkillService   │  │ InterviewService│   │
│   └────────────────┘  └────────────────┘  └────────────────┘   │
│   ┌────────────────┐  ┌────────────────┐                        │
│   │ 成果服务       │  │ 记忆服务       │                        │
│   │ Achievement    │  │ MemoryService  │                        │
│   └────────────────┘  └────────────────┘                        │
├─────────────────────────────────────────────────────────────────┤
│                        AI 引擎层                                │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                  Python Context-OS                      │   │
│   │   Pipeline: Intent → Orchestrator → Collection →       │   │
│   │   Builder → Optimizer → Packager → LLM → Feedback      │   │
│   │                                                         │   │
│   │   Memory: Working / Short-Term / Long-Term /           │   │
│   │   Episodic / Semantic                                  │   │
│   └─────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                        数据层                                    │
│   ┌──────────┐   ┌────────┐   ┌────────┐   ┌─────────┐        │
│   │PostgreSQL│   │ChromaDB│   │ Redis  │   │  MinIO  │        │
│   └──────────┘   └────────┘   └────────┘   └─────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 技术栈选择

| 层级 | 技术 | 选型理由 |
|---|---|---|
| 前端 | Vue3 + TypeScript | 类型安全，生态成熟，组件丰富 |
| UI 框架 | Element Plus | 企业级组件库，开箱即用 |
| 后端 | SpringBoot 3.x | Java 生态标准，社区成熟 |
| ORM | MyBatis-Plus | SQL 可控，性能优秀 |
| AI 引擎 | Python (Context-OS) | 复用现有记忆系统，LangChain 生态完善 |
| 向量数据库 | ChromaDB | 轻量级，Python 集成好 |
| 缓存 | Redis | 会话缓存、热点数据 |
| 文件存储 | MinIO | 对象存储，支持 S3 协议 |
| 消息队列 | RabbitMQ | 异步处理、解耦 |

### 5.3 服务间通信

```
SpringBoot 服务 ──────HTTP/gRPC──────> Python AI 服务
                                          │
                    PostgreSQL ◄──────────┤
                    ChromaDB   ◄──────────┤
```

**关键接口：**

| 接口 | 路径 | 描述 |
|---|---|---|
| 面试对话 | `/api/v1/interview/chat` | 发送用户回答，获取 AI 反馈 |
| Skill 匹配 | `/api/v1/skill/match` | 根据输入匹配最佳 Skill |
| 记忆检索 | `/api/v1/memory/retrieve` | 检索用户相关记忆 |
| 记忆更新 | `/api/v1/memory/update` | 更新记忆系统 |
| 报告生成 | `/api/v1/report/generate` | 生成面试报告 |

### 5.4 核心类设计（Java）

```java
// 面试服务
@Service
public class InterviewService {
    public InterviewSession createSession(String userId, String skillId);
    public InterviewTurn askQuestion(String sessionId);
    public InterviewTurn submitAnswer(String sessionId, String answer);
    public InterviewReport finishSession(String sessionId);
}

// Skill 服务
@Service
public class SkillService {
    public List<Skill> listSkills(String industry, String position);
    public Skill getSkill(String skillId);
    public void installSkill(String userId, String skillId);
    public void uninstallSkill(String userId, String skillId);
    public Skill matchSkill(String userId, String userInput);
}

// 记忆服务（调用 Python）
@Service
public class MemoryService {
    public List<MemoryItem> retrieve(String userId, String query, int topK);
    public void update(String userId, MemoryUpdateRequest request);
    public UserProfile getProfile(String userId);
}

// AI 客户端
@Component
public class AIClient {
    public String chat(ChatRequest request);
    public String evaluate(EvaluateRequest request);
    public String generateQuestion(QuestionRequest request);
}
```

---

## 六、关键差异化设计

### 6.1 记忆驱动的自适应学习

```
用户首次面试 → 识别弱点（如"MySQL 优化"）
                  │
                  ▼
         后续面试优先出题 → 强化训练
                  │
                  ▼
         持续追踪掌握度变化
                  │
                  ▼
         掌握度 >= 80% → 降低该知识点权重
         掌握度 < 50% → 增加训练频次
```

### 6.2 知识图谱构建

```
面试过程中自动构建知识图谱：

"Java" ─── extends ───> "JVM"
    │                       │
    │ uses                  │ manages
    ▼                       ▼
"Spring" ─── manages ───> "GC"
    │
    │ integrates
    ▼
"MySQL" ─── optimizedBy ───> "Index"
```

### 6.3 情感分析（可选扩展）

```
用户回答 → 语音转文字 → 情感分析
                            │
                            ├─ 语速分析 → 建议调整表达节奏
                            ├─ 停顿分析 → 建议更流畅的表达
                            └─ 情绪分析 → 建议保持自信
```

---

## 七、产品路线图

### Phase 1：MVP（基础功能）

- [ ] 用户注册/登录
- [ ] Skill 技能中心（浏览、搜索、安装）
- [ ] 主对话界面（面试模拟）
- [ ] 基础记忆系统（Working + Short-Term）
- [ ] 面试报告生成
- [ ] 成果保存与下载

### Phase 2：核心差异化

- [ ] 完整 5 层记忆系统
- [ ] 自适应出题（基于记忆）
- [ ] 能力画像与趋势分析
- [ ] 知识图谱构建
- [ ] 数据源上传与关联

### Phase 3：高级功能

- [ ] 语音面试模拟
- [ ] 情感分析反馈
- [ ] 多人协作面试
- [ ] 企业定制版
- [ ] 移动端适配

---

## 八、数据隐私与安全

### 8.1 数据隔离

- 用户数据按 `user_id` 严格隔离
- Skill 数据共享（公共技能市场）
- 知识库数据可设置公开/私有

### 8.2 数据加密

- 传输层：HTTPS
- 存储层：敏感字段 AES-256 加密
- 向量数据：脱敏处理

### 8.3 用户控制

- 用户可随时删除个人数据
- 可导出所有个人数据
- 可控制记忆系统的使用范围

---

## 九、总结

本产品的核心竞争力在于**记忆系统**——通过 5 层记忆架构，实现：

1. **持续追踪**：记住用户每一次面试表现
2. **个性化**：基于记忆自适应出题和反馈
3. **知识积累**：从面试中构建个人知识图谱
4. **可见进步**：通过能力趋势图展示成长

这是传统面试产品无法实现的核心差异化能力。
