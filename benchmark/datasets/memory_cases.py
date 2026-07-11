"""记忆系统 Benchmark 测试用例。

每个 TestCase 包含:
    - id: 唯一标识
    - questions: 按顺序的问题列表
    - expected_keywords_per_q: 每轮的关键词
    - ground_truth: 标准答案文本
    - expected_json: 结构化期望数据（可选）
    - tags: 标签列表
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TestCase:
    """测试用例。

    Fields:
        id: 唯一标识。
        questions: 按顺序的问题列表。
        description: 描述。
        expected_keywords_per_q: 每轮的关键词列表。
        expected_intent: 每轮的期望意图（如 STORE_FACT, UPDATE_FACT, QUERY_FACT 等）。
        expected_json: 标准答案结构化 JSON（主要评分依据）。
        ground_truth: 标准答案文本（备用，逐渐废弃）。
        tags: 标签列表。
    """
    id: str
    questions: list[str]
    description: str
    expected_keywords_per_q: list[list[str]]
    expected_intent: Optional[list[str]] = None
    expected_json: Optional[dict[str, Any]] = None
    ground_truth: str = ""
    tags: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# T1: 多用户财务流水 — 4 人交错 + 冲正 + 共享账
# ═══════════════════════════════════════════════════════════════════

T1 = TestCase(
    id="T1",
    questions=[
        "【初始状态】Alice 的工资卡有 5000 元，Bob 的储蓄卡有 10000 元，"
        "Charlie 的账户有 2000 元。Diana 新开了两个账户：A 账户（活期）存了 3000 元，"
        "B 账户（定期）存了 10000 元，活期利率 0.3%，定期利率 2.5%。",
        "【收入 1】Alice 工资到账 8000 元。",
        "【支出 1】Bob 交了房租 3000 元。",
        "【收入 2】Charlie 收到退款 500 元。",
        "【支出 2】Alice 买手机花了 5999 元。",
        "【收入 3】Bob 报销餐费 200 元入账。",
        "【冲正】上周 Charlie 有一笔 800 元的转账被错误扣款，银行今天发起了冲正，资金已退回。",
        "【收入 4】Alice 理财收益 300 元到账。",
        "【收入 5】Bob 年终奖 20000 元入账。",
        "【共享支出】Alice、Bob、Charlie 三人聚餐花费 900 元，AA 制均摊。",
        "【支出 3】Alice 交水电费 200 元。Diana 的活期账户产生了一个季度的利息。",
        "【收入 6】Charlie 卖二手物品赚了 800 元。",
        "【支出 4】Bob 买电脑花了 8999 元。",
        "请回顾前面的所有记录，回答以下回顾性问题：\n"
        "1. 第一笔收入是谁的、来源是什么、金额是多少？\n"
        "2. 第一笔支出是谁的、支付名目是什么、金额是多少？\n"
        "3. 是否有因银行错误扣款而发起的资金退回，涉及谁、金额多少？\n"
        "4. 有没有人购买过电子产品，是谁、花了多少钱？\n"
        "5. 有没有人收到过年度奖金收入，是谁、金额多少？\n"
        "6. 有没有三个人共同分摊的聚餐花费，总金额多少？\n"
        "7. 所有支出中，金额最小的一笔是谁的、是多少？\n"
        "8. 有没有人购买过便携式计算机，是谁、花了多少钱？\n"
        "9. 有没有人交过公用事业类费用，是谁、交了多少钱？",
    ],
    description="多用户财务追踪（14轮）：13轮交易录入 + 最终回顾性事实召回（无需数值计算）",
    tags=["memory", "multi_user", "financial", "recall"],
    expected_intent=[
        "STORE_FACT", "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT",
        "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT",
        "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT",
        "UPDATE_FACT", "QUERY_FACT",
    ],
    expected_keywords_per_q=[
        ["5000", "Alice", "10000", "Bob", "2000", "Charlie", "3000", "10000", "Diana"],
        ["8000", "Alice"],
        ["3000", "Bob"],
        ["500", "Charlie"],
        ["5999", "Alice"],
        ["200", "Bob"],
        ["冲正", "800", "Charlie"],
        ["300", "Alice"],
        ["20000", "Bob"],
        ["900", "AA", "均摊"],
        ["200", "Alice", "利息", "Diana"],
        ["800", "Charlie"],
        ["8999", "Bob"],
        # Q14 关键词全部是 Q1-Q13 中的具体事实，且均不作为子字符串出现在 Q14 问题文本中
        # 验证：8000/alice/工资/3000/bob/房租/冲正/charlie/800/5999/20000/900/aa/200/水电费/8999/电脑
        # 均不在 Q14 问句中 → memory_kw 过滤后不会丢失任何关键词
        ["8000", "Alice", "工资", "3000", "Bob", "房租", "冲正", "Charlie",
         "800", "5999", "20000", "900", "AA", "200", "水电费", "8999", "电脑"],
    ],
    expected_json={
        "第一笔收入": "Alice 工资 8000元",
        "第一笔支出": "Bob 房租 3000元",
        "冲正": "Charlie 800元",
        "电子产品": "Alice 买手机 5999元",
        "年度奖金": "Bob 20000元",
        "聚餐": "900元 AA",
        "最小支出": "200元",
        "计算机": "Bob 电脑 8999元",
        "公用事业": "Alice 水电费 200元",
    },
)

# ═══════════════════════════════════════════════════════════════════
# T2: 嵌套配置依赖 — 3 层传递依赖 + 级联回滚
# ═══════════════════════════════════════════════════════════════════

T2 = TestCase(
    id="T2",
    questions=[
        "【初始化】服务器配置如下，请逐项记住："
        "连接池大小=10，超时=30s，日志级别=INFO，缓存大小=512MB，"
        "最大连接数=200，读超时=10s。"
        "规则：①改连接池大小 → 超时重置为 30s；"
        "②改超时 → 读超时重置为 10s；"
        "③改最大连接数 → 连接池大小重置为 10（→ 触发规则①）。",
        "把连接池大小改为 20（超时→30s，读超时→10s 因为规则②被触发）。",
        "把超时改为 60s（读超时→10s）。",
        "把日志级别改为 DEBUG，缓存大小改为 1024MB。",
        "把最大连接数改为 500（→ 连接池→10 → 超时→30s → 读超时→10s）。",
        "把超时改为 45s，连接池改为 30（超时→30s，读超时→10s）。",
        "把缓存大小改为 2048MB，读超时改为 30s。",
        "【回滚操作】将连接池大小回滚到 3 轮前的值（第 3 轮时连接池=20）。"
        "（→ 超时→30s，读超时→10s）",
        "把日志级别改为 WARN，最大连接数改为 300（→ 连接池→10 → 级联全部重置）。",
        "现在告诉我：当前连接池大小、超时、日志级别、缓存大小、最大连接数、读超时分别是多少？"
        "连接池被间接重置过几次（通过规则③触发）？"
        "第 8 轮的回滚操作把连接池恢复到了第几轮时的值？",
    ],
    description="3层传递依赖+级联回滚（10 轮）：A→B→C 级联重置+历史快照回滚",
    tags=["memory", "config", "cascade"],
    expected_intent=[
        "STORE_FACT", "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT",
        "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT",
        "UPDATE_FACT", "QUERY_FACT",
    ],
    expected_keywords_per_q=[
        ["10", "30", "INFO", "512", "200", "10"],
        ["20"],
        ["60"],
        ["DEBUG", "1024"],
        ["500", "10", "30", "10"],
        ["45", "30", "30", "10"],
        ["2048", "30"],
        ["20", "回滚", "第 3 轮"],
        ["WARN", "300", "10", "30", "10"],
        ["10", "30", "WARN", "2048", "300", "10", "2", "3"],
    ],
    expected_json={
        "连接池": "10",
        "超时": "30s",
        "日志": "WARN",
        "缓存": "2048MB",
        "最大连接": "300",
        "读超时": "10s",
        "间接重置次数": "2",
    },
)

# ═══════════════════════════════════════════════════════════════════
# T3: 复杂人际网络 — 5 人 10 对关系 + 信息更正
# ═══════════════════════════════════════════════════════════════════

T3 = TestCase(
    id="T3",
    questions=[
        "【初始关系】Alice 和 Bob 是大学室友兼好友，一起创业做电商。"
        "Charlie 是他们的同班同学，和 Eve 是兄妹。"
        "Diana 是转系来的学姐，目前只和 Charlie 有交流。"
        "Eve 是新生，和哥哥 Charlie 关系很好，和其他人还不认识。",
        "Alice 和 Charlie 合作了一个 AI 项目，每周在实验室待到很晚，成了密切的合作伙伴。",
        "Bob 和 Diana 因为一场辩论赛互相欣赏，开始频繁约会。",
        "【传闻】有人传 Alice 在挖角 Charlie 想让他离开 Bob 的创业团队， Bob 听说后对 Alice 产生了怀疑。",
        "Alice 和 Bob 因为公司的股份分配问题大吵一架，关系降到冰点，Charlie 尝试调解但失败。",
        "Eve 加入了 Alice 和 Charlie 的 AI 项目组，和 Alice 成了好朋友。",
        "Diana 和 Eve 在同一个社团活动中认识，发现彼此很投缘。",
        "【澄清】Alice 实际上是在为 Charlie 介绍另一个投资机会，根本不是挖角。Bob 知道真相后向 Alice 道歉，两人和解。",
        "【三角关系】Bob 开始对 Eve 产生好感，经常找借口去 AI 项目组。"
        "但 Eve 似乎不感冒。同时 Diana 发现 Bob 还在和她约会的同时去追 Eve，非常生气。",
        "请回顾前面的人际关系记录，回答以下回顾性问题：\n"
        "1. 哪两个人是大学室友并共同创立了公司？\n"
        "2. 谁和谁共同参与智能相关的课题研究？\n"
        "3. 谁和谁因为一场校际口才竞赛而开始交往？\n"
        "4. 传入的消息称谁在试图从团队中挖走谁？后来这条消息被证实是什么？\n"
        "5. 谁和谁因为公司的所有权分配问题发生过争吵？\n"
        "6. 谁加入了课题研究组之后和谁变得很亲密？\n"
        "7. 谁和谁在课外兴趣小组里认识并彼此投缘？\n"
        "8. 最终谁对谁产生了一厢情愿的情愫，导致了什么状况？",
    ],
    description="5人关系追踪（10轮）：9轮关系录入 + 最终回顾性事实召回",
    tags=["memory", "social", "relationship", "recall"],
    expected_intent=[
        "STORE_FACT", "UPDATE_FACT", "UPDATE_FACT", "STORE_FACT",
        "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT", "UPDATE_FACT",
        "UPDATE_FACT", "QUERY_FACT",
    ],
    expected_keywords_per_q=[
        ["Alice", "Bob", "室友", "创业", "Charlie", "Eve", "兄妹", "Diana", "学姐"],
        ["Alice", "Charlie", "合作", "AI"],
        ["Bob", "Diana", "辩论", "约会"],
        ["传闻", "挖角", "Alice", "Charlie"],
        ["Alice", "Bob", "吵架", "股份"],
        ["Eve", "Alice", "好友", "AI"],
        ["Diana", "Eve", "社团"],
        ["澄清", "投资", "和解"],
        ["Bob", "Eve", "好感", "Diana", "生气"],
        # Q10 关键词全部是 Q1-Q9 中的具体事实，且均不在 Q10 问题文本中出现
        ["Alice", "Bob", "室友", "创业", "Charlie", "AI", "合作",
         "Diana", "辩论", "约会", "挖角", "传闻", "投资", "澄清",
         "股份", "吵架", "Eve", "好友", "社团", "好感", "三角"],
    ],
    expected_json={
        "室友创业": "Alice Bob",
        "课题合作": "Alice Charlie",
        "交往": "Bob Diana",
        "挖角传闻": "Alice Charlie 投资",
        "争吵": "Alice Bob 股份",
        "好友": "Eve Alice",
        "社团": "Diana Eve",
        "三角": "Bob Diana Eve",
    },
    ground_truth="",
)

# ═══════════════════════════════════════════════════════════════════
# T4: 系统状态 — 10 指标 + 复合异常 + SLA 基线
# ═══════════════════════════════════════════════════════════════════

T4 = TestCase(
    id="T4",
    questions=[
        "【初始基线】服务器监控基线如下（SLA 红线），请逐项记住："
        "CPU=50%（红线 90%），内存=60%（红线 85%），磁盘已用 300GB/500GB（红线 90%），"
        "网络延迟=15ms（红线 100ms），QPS=1200（红线 8000），错误率=0.1%（红线 1%），"
        "GC 暂停时间=50ms（红线 200ms），线程数=200（红线 500），"
        "连接数=150（红线 400），磁盘 IOPS=2000（红线 10000）。",
        "CPU 升到 75%，QPS 升到 3000（业务高峰）。",
        "内存升到 85%，磁盘升到 380GB（内存触红线！但未超过 85%→刚好在边界）。",
        "【复合异常】数据库连接数飙升到 450（超红线），同时 CPU 升到 92%（超红线），"
        "错误率升到 3%（超红线），网络延迟升到 180ms（超红线）。",
        "紧急扩容后恢复：连接数→200，CPU→65%，错误率→0.3%，延迟→30ms。",
        "【瞬态异常】GC 暂停时间瞬间跳到 500ms，但下一轮自动回落到 80ms，未人工介入。",
        "磁盘升到 490GB（超磁盘红线 98%！），线程数升到 450。",
        "运维清理了日志和临时文件，磁盘降到 350GB，线程数降到 280。",
        "CPU 升到 88%（接近红线），QPS 升到 7500（接近红线）。",
        "请回顾前面的监控记录，回答以下回顾性问题：\n"
        "异常告警中，首次出现的复合异常是在第几轮？\n"
        "复合异常事件中，同时触发了哪四个指标的险情？\n"
        "短时间内短暂突发的那个尖峰发生在哪个指标上，它自动恢复了吗？\n"
        "存储空间的初始配额是多少GB，预警阈值是多少百分比？\n"
        "哪一轮出现了逼近存储上限的情况，运维做了什么操作来解决？\n"
        "初始状态下，每秒请求多少个，线程数是多少？\n"
        "最终，红线临界值被突破的事件一共统计到了多少次？",
    ],
    description="10指标监控追踪（10轮）：9轮状态录入 + 最终回顾性事实召回",
    tags=["memory", "monitoring", "sla", "recall"],
    expected_intent=[
        "STORE_FACT", "UPDATE_FACT", "UPDATE_FACT", "STORE_FACT",
        "UPDATE_FACT", "STORE_FACT", "UPDATE_FACT", "UPDATE_FACT",
        "UPDATE_FACT", "QUERY_FACT",
    ],
    expected_keywords_per_q=[
        ["50", "60", "300", "500", "15", "1200", "0.1", "50", "200", "150", "2000"],
        ["75", "3000"],
        ["85", "380"],
        ["450", "92", "3", "180", "复合", "红线"],
        ["200", "65", "0.3", "30"],
        ["GC", "500", "80", "瞬态"],
        ["490", "450"],
        ["350", "280"],
        ["88", "7500"],
        # Q10 关键词均为 Q1-Q9 的具体事实，均不在 Q10 问题文本中
        ["50", "60", "300", "500", "15", "1200", "0.1", "200", "150",
         "4", "CPU", "内存", "错误率", "延迟", "扩容", "GC",
         "490", "6", "清理", "7", "90", "85", "100"],
    ],
    ground_truth="",
    expected_json={
        "初始CPU": "50%",
        "初始内存": "60%",
        "初始磁盘配额": "500GB",
        "初始磁盘使用": "300GB",
        "初始延迟": "15ms",
        "初始QPS": "1200",
        "初始错误率": "0.1%",
        "线程数": "200",
        "连接数": "150",
        "红线CPU": "90%",
        "红线内存": "85%",
        "红线延迟": "100ms",
        "复合异常轮次": "4",
        "瞬态异常指标": "GC",
        "磁盘告警轮次": "6",
        "SLA违规次数": "7",
    },
)

# ═══════════════════════════════════════════════════════════════════
# T5: 双轨时序因果推理 — 并行事件链 + 交叉影响
# ═══════════════════════════════════════════════════════════════════

T5 = TestCase(
    id="T5",
    questions=[
        "【A 链 - 数据库故障】周一 8:00：主库复制延迟从 100ms 飙升到 30s，DBA 团队收到告警。",
        "【A 链】周一 10:00：排查发现是 binlog 文件磁盘空间满了，导致从库无法同步。",
        "【B 链 - 网络攻击】周一 14:00：安全团队发现异常流量模式，有外部 IP 正在对 API 网关发起 DDoS 攻击。",
        "【A 链】周一 16:00：清理磁盘 + 扩容完成，复制延迟恢复到 200ms。但 DBA 发现由于长时间同步延迟，有约 15 分钟的数据差异需要比对。",
        "【B 链】周一 18:00：WAF 规则已更新，DDoS 流量被拦截 90%，但攻击者开始变换 IP 和攻击向量。",
        "【交叉影响】周一 20:00：攻击者转向攻击备份系统，导致当天的自动备份失败。DBA 需要在数据比对的同时处理备份问题。",
        "【A 链延续】周二 02:00：数据差异比对完成，修复了 237 条不一致记录。",
        "【B 链延续】周二 06:00：安全团队部署了自动 IP 黑名单+速率限制，DDoS 攻击被完全遏制。",
        "【交叉修复】周二 10:00：备份系统恢复，开始补跑昨天的全量备份。原本计划周二的版本发布因故取消。",
        "【收尾】周二 18:00：全量备份完成，所有系统恢复正常。"
        "请精准回答：\n"
        "a) 数据库故障链（A 链）的完整时间线，从发现到修复的 4 个关键节点\n"
        "b) DDoS 攻击链（B 链）的关键节点\n"
        "c) 两条事件链在哪一点交叉影响的？\n"
        "d) 原计划周二的什么事件没有发生？\n"
        "e) 从第一次告警到完全恢复用了多长时间？",
    ],
    description="双轨并行+交叉影响+非事件识别（10 轮）：双链时序推理+交叉点+非事件",
    tags=["memory", "timeline", "reasoning"],
    expected_intent=[
        "STORE_FACT", "STORE_FACT", "STORE_FACT", "STORE_FACT",
        "STORE_FACT", "STORE_FACT", "STORE_FACT", "STORE_FACT",
        "STORE_FACT", "QUERY_FACT",
    ],
    expected_keywords_per_q=[
        ["A", "周一", "8:00", "复制", "30s"],
        ["周一", "10:00", "binlog", "磁盘"],
        ["B", "周一", "14:00", "DDoS", "攻击"],
        ["周一", "16:00", "扩容", "15 分钟", "差异"],
        ["周一", "18:00", "WAF", "90%"],
        ["交叉", "备份", "失败", "DBA"],
        ["周二", "02:00", "237", "不一致"],
        ["周二", "06:00", "遏制"],
        ["备份", "恢复", "版本发布", "取消"],
        ["周一", "8:00", "周二", "18:00", "34", "交叉", "备份", "版本发布", "取消"],
    ],
    ground_truth="",
    expected_json={
        "A链时间线": "周一8:00告警→10:00排查binlog→16:00扩容→周二02:00修复237条记录",
        "B链时间线": "周一14:00DDoS攻击→18:00WAF拦截90%→周二06:00完全遏制",
        "交叉影响点": "周一20:00攻击者转向备份系统导致备份失败",
        "未发生事件": "版本发布取消",
        "总耗时": "34小时（周一8:00至周二18:00）",
    },
)

# ═══════════════════════════════════════════════════════════════════
# T6: 跨 Session 长程记忆 — 4 Session + 诱导性问题
# ═══════════════════════════════════════════════════════════════════

T6 = TestCase(
    id="T6",
    questions=[
        "【Session 1 - 项目 Alpha】Alpha 技术栈确定："
        "前端 React 18 + TypeScript，后端 Go + Gin，数据库 PostgreSQL 15，"
        "缓存 Redis 7，消息队列 RabbitMQ。",
        "PostgreSQL 选型原因：需要 PostGIS 地理空间查询 + 高并发写入（5000 QPS），MVCC 机制更适合我们的读写比例（7:3）。",
        "部署方案：Docker + Kubernetes，3 副本自动扩缩容，目标可用性 99.9%，API 采用 REST + JWT + Swagger。",
        "【Session 2 - 项目 Beta，完全不同】Beta 技术栈完全不同："
        "前端 Vue 3 + JavaScript，后端 Python FastAPI，数据库 MySQL 8.0，缓存 Memcached，消息队列 Kafka。",
        "MySQL 选型原因：Beta 项目是内容管理系统，主要是 CRUD 操作，MySQL 的 InnoDB 引擎对事务支持好。",
        "Beta 部署方案：单机 Docker Compose，2 副本，目标可用性 99.5%，API 采用 GraphQL + API Key 认证。",
        "【Session 3 - 旅行计划，数字干扰】我计划明年去日本旅行，总预算 15000 元，12 月 15 日出发，12 月 22 日回。",
        "住宿 Airbnb 每晚 500 元，一共 7 晚，行程东京 3 天→京都 2 天→大阪 2 天。",
        "【Session 3 细节】JR Pass 7 天通票，买了旅游保险 300 元。信用卡额度 50000 元，准备带 5000 元现金。",
        "【Session 4 - 回到 Alpha】先问 Alpha：前端用的什么框架？",
        "Alpha 的数据库选型是 MySQL 还是 PostgreSQL？选它的两个原因是什么？（注意：Beta 用的数据库不同）",
        "Beta 的 API 认证方式和 Alpha 有什么不同？两个项目的部署架构区别是什么？",
        "Alpha 的消息队列选了什么？Beta 的呢？",
        "旅行计划的出发日期是哪一天？（和项目无关，只是想确认记忆是否有交叉污染）",
        "请回顾前面的所有技术记录，依次回答：\n"
        "1. Alpha的前端框架名称\n"
        "2. Alpha后端使用的编程语言\n"
        "3. Alpha选用的数据存储产品\n"
        "4. Alpha用的缓存中间件\n"
        "5. Alpha用的消息中间件\n"
        "6. Beta的前端框架名称\n"
        "7. Beta后端使用的编程语言\n"
        "8. Beta选用的数据存储产品\n"
        "9. Beta用的消息队列产品\n"
        "10. 旅行计划的出发时间（月日）",
    ],
    description="4 Session长程记忆（15轮）：跨Session检索+技术栈事实召回",
    tags=["memory", "cross_session", "interference", "recall"],
    expected_intent=[
        "STORE_FACT", "STORE_FACT", "STORE_FACT",
        "STORE_FACT", "STORE_FACT", "STORE_FACT",
        "STORE_FACT", "STORE_FACT", "STORE_FACT",
        "QUERY_FACT", "QUERY_FACT", "QUERY_FACT",
        "QUERY_FACT", "QUERY_FACT", "QUERY_FACT",
    ],
    expected_keywords_per_q=[
        ["React", "Go", "PostgreSQL", "Redis", "RabbitMQ", "Alpha"],
        ["PostGIS", "MVCC", "5000", "7:3"],
        ["Docker", "Kubernetes", "99.9", "REST", "JWT"],
        ["Vue", "Python", "FastAPI", "MySQL", "Memcached", "Kafka", "Beta"],
        ["InnoDB", "CRUD", "事务"],
        ["Docker Compose", "99.5", "GraphQL", "API Key"],
        ["日本", "15000", "12 月 15"],
        ["Airbnb", "500", "7", "东京", "京都", "大阪"],
        ["JR Pass", "300", "50000", "5000"],
        ["React", "前端"],
        ["PostgreSQL", "PostGIS", "MVCC", "高并发"],
        ["JWT", "API Key", "Docker", "Kubernetes", "Docker Compose"],
        ["RabbitMQ", "Alpha", "Kafka", "Beta"],
        ["12 月 15 日"],
        # Q15 关键词均为 Q1-Q14 中的技术栈事实，均不在 Q15 问题文本中
        ["React", "Go", "PostgreSQL", "Redis", "RabbitMQ",
         "Vue", "Python", "MySQL", "Kafka", "12月15"],
    ],
    ground_truth="",
    expected_json={
        "Alpha前端": "React",
        "Alpha后端": "Go",
        "Alpha数据库": "PostgreSQL",
        "Alpha缓存": "Redis",
        "Alpha消息队列": "RabbitMQ",
        "Beta前端": "Vue",
        "Beta后端": "Python",
        "Beta数据库": "MySQL",
        "Beta消息队列": "Kafka",
        "旅行日期": "12月15日",
    },
)

MEMORY_TEST_CASES = [T1, T2, T3, T4, T5, T6]
