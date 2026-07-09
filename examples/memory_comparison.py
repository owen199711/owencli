"""记忆系统对比测试：无记忆 (SimpleAgent) vs 有记忆 (Context-OS MemoryAgent)。

运行:
    python examples/memory_comparison.py

测试场景:
    6 个极限复杂度场景，每个包含 10~15 轮连续对话。
    专为压测 LTM 的跨轮检索、实体分离、因果推理、时序双链、干扰排除能力。

    T1 - 多用户财务+冲正+共享账（14 轮）：4 人交错收支+冲正回溯+AA 分摊
    T2 - 3 层传递依赖+级联回滚（10 轮）：A→B→C 级联重置+历史快照回滚
    T3 - 5 人社交网络+传闻更正+三角关系（10 轮）：错误信息识别+关系结构分析
    T4 - 10 指标+复合异常+SLA 基线（10 轮）：复合异常识别+瞬态异常+SLA 统计
    T5 - 双轨并行+交叉影响+非事件（10 轮）：双链时序推理+交叉点+非事件识别
    T6 - 4 Session+诱导性提问（15 轮）：跨 Session 检索+干扰排除+诱导识别
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional
from datetime import datetime
import json


# ═══════════════════════════════════════════════════════════════════
# Agent A: 无记忆系统 — 每次调用都是独立的
# ═══════════════════════════════════════════════════════════════════

class SimpleAgent:
    """无记忆 Agent — 每次调用完全独立，不给任何上下文。

    模拟"无记忆系统"的行为：
    - 无 conversation_history
    - 无检索 / 无 Context-OS Pipeline
    - 只传当前输入的原始文本给 LLM
    """

    def __init__(self, llm_client: Any):
        self.llm_client = llm_client
        print("[SimpleAgent] 已初始化（无记忆 — 每次调用完全独立）")

    async def chat(self, user_input: str) -> str:
        """对话 — 完全无上下文，只传当前输入。

        Args:
            user_input: 用户输入。

        Returns:
            LLM 回复。
        """
        prompt = f"User: {user_input}\nAssistant:"
        response = await self.llm_client.complete(prompt, max_tokens=2000)
        return str(response)


# ═══════════════════════════════════════════════════════════════════
# Agent B: Context-OS 完整记忆系统
# ═══════════════════════════════════════════════════════════════════

class MemoryAgent:
    """具备完整 Context-OS 记忆系统的 Agent。

    使用:
        - WorkingMemory: 当前对话活跃上下文
        - ShortTermMemory: Session 级记忆（PG 持久化）
        - LongTermMemory: 跨 Session 长期知识
        - ContextBuilder: 自动构建 UnifiedContext
        - ContextOptimizer: Token 排序压缩
    """

    def __init__(
        self,
        llm_client: Any,
        db_path: Optional[str] = None,
        embedding_provider: Any = None,
    ):
        from context_os import ContextOSPipeline
        from context_os.core.models import LLMProvider

        # 自动检测 provider
        provider_name = type(llm_client).__name__.lower()
        if "anthropic" in provider_name:
            provider = LLMProvider.CLAUDE
        elif "openai" in provider_name:
            provider = LLMProvider.OPENAI
        elif "deepseek" in provider_name:
            provider = LLMProvider.DEEPSEEK
        else:
            provider = LLMProvider.CLAUDE

        self.pipeline = ContextOSPipeline(
            llm_client=llm_client,
            provider=provider,
            db_path=db_path,
            session_id=f"test-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            user_id="memory-test",
            embedding_provider=embedding_provider,
        )
        self._initialized = False
        emb_info = f" + {type(embedding_provider).__name__}" if embedding_provider else ""
        print(f"[MemoryAgent] 已初始化（{provider.value}{emb_info})")

    async def chat(self, user_input: str) -> str:
        """对话 — 走完整 Pipeline。

        Args:
            user_input: 用户输入。

        Returns:
            LLM 回复。
        """
        if not self._initialized:
            await self.pipeline._ensure_store()
            self._initialized = True

        result = await self.pipeline.run(user_input)
        return result["response"]

    async def close(self):
        await self.pipeline.close()


# ═══════════════════════════════════════════════════════════════════
# 测试场景
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TestCase:
    """测试用例。"""
    id: str
    questions: list[str]
    description: str
    # 每个 Q 应包含的关键词（粗略评估）
    expected_keywords_per_q: list[list[str]]
    # 最后一问的标准答案（精确匹配）
    ground_truth: str = ""


TEST_CASES = [
    # ══════════════════════════════════════════════════════════════
    # T1: 多用户财务流水 — 4 人交错 + 冲正 + 共享账
    # ══════════════════════════════════════════════════════════════
    # 复杂度升级：
    #   1. 4 人（Alice/Bob/Charlie/Diana）交错 14 轮
    #   2. Diana 初始余额需从"账户类型"信息中推断（高/低风险账户不同利率）
    #   3. 第 7 轮出现"冲正"（退款逆转），需回溯修正历史
    #   4. 第 10 轮有"共享支出"（AA 制），需要跨角色推导
    #   5. 最终问 4 人余额 + 谁余额变动最大 + 哪笔交易被冲正
    # ══════════════════════════════════════════════════════════════
    TestCase(
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
            "【冲正】上周 Charlie 有一笔 800 元的转账被错误扣款，"
            "银行今天发起了冲正，资金已退回 Charlie 账户。",
            "【收入 4】Alice 理财收益 300 元到账。",
            "【收入 5】Bob 年终奖 20000 元入账。",
            "【共享支出】Alice、Bob、Charlie 三人聚餐花费 900 元，AA 制均摊。",
            "【支出 3】Alice 交水电费 200 元。Diana 的活期账户产生了一个季度的利息。",
            "【收入 6】Charlie 卖二手物品赚了 800 元。",
            "【支出 4】Bob 买电脑花了 8999 元。",
            "请分别告诉我 Alice、Bob、Charlie、Diana 四人当前的可用余额分别是多少？"
            "从第 1 轮到第 13 轮，谁的余额变动幅度最大？"
            "哪笔交易属于冲正操作，涉及谁？",
        ],
        description="多用户财务+冲正+共享账（14 轮）：4 人交错追踪+冲正回溯+利率计算",
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
            ["7101", "18201", "2900", "余额", "变动", "冲正"],
        ],
        ground_truth="Alice=7101, Bob=18201, Charlie=2900",
    ),

    # ══════════════════════════════════════════════════════════════
    # T2: 嵌套配置依赖 — 3 层传递依赖 + 级联回滚
    # ══════════════════════════════════════════════════════════════
    # 复杂度升级：
    #   1. 新增规则链：改 A → 重置 B；改 B → 重置 C；改 C 不影响 A/B
    #   2. 某轮出现"回滚"（恢复某个配置到 3 轮前的值），需追踪历史快照
    #   3. 某一轮同时修改多个配置，需判断哪个重置被触发
    #   4. 最终问当前值 + 每项被改次数 + 回滚操作是谁触发的
    # ══════════════════════════════════════════════════════════════
    TestCase(
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
        ground_truth="连接池=10 超时=30s 日志=WARN 缓存=2048MB 最大连接=300 读超时=10s",
    ),

    # ══════════════════════════════════════════════════════════════
    # T3: 复杂人际网络 — 5 人 10 对关系 + 信息更正
    # ══════════════════════════════════════════════════════════════
    # 复杂度升级：
    #   1. 5 人 → 10 对关系（理论上限翻倍）
    #   2. 第 5 轮引入"传闻/错误信息"，第 8 轮被澄清
    #   3. 出现三角关系（A 喜欢 B，B 喜欢 C）
    #   4. 最终问：特定配对关系演变 + 识别被更正的信息 + 三角关系识别
    # ══════════════════════════════════════════════════════════════
    TestCase(
        id="T3",
        questions=[
            "【初始关系】Alice 和 Bob 是大学室友兼好友，一起创业做电商。"
            "Charlie 是他们的同班同学，和 Eve 是兄妹。"
            "Diana 是转系来的学姐，目前只和 Charlie 有交流。"
            "Eve 是新生，和哥哥 Charlie 关系很好，和其他人还不认识。",
            "Alice 和 Charlie 合作了一个 AI 项目，每周在实验室待到很晚，成了密切的合作伙伴。",
            "Bob 和 Diana 因为一场辩论赛互相欣赏，开始频繁约会。",
            "【传闻】有人传 Alice 在挖角 Charlie 想让他离开 Bob 的创业团队，"
            "Bob 听说后对 Alice 产生了怀疑。",
            "Alice 和 Bob 因为公司的股份分配问题大吵一架，关系降到冰点，"
            "Charlie 尝试调解但失败。",
            "Eve 加入了 Alice 和 Charlie 的 AI 项目组，和 Alice 成了好朋友。",
            "Diana 和 Eve 在同一个社团活动中认识，发现彼此很投缘。",
            "【澄清】Alice 实际上是在为 Charlie 介绍另一个投资机会，"
            "根本不是挖角。Bob 知道真相后向 Alice 道歉，两人和解。",
            "【三角关系】Bob 开始对 Eve 产生好感，经常找借口去 AI 项目组。"
            "但 Eve 似乎对 Charlie 的合伙人——也就是 Alice——的创业搭档 Bob 并不感冒。"
            "同时 Diana 发现 Bob 还在和她约会的同时去追 Eve，非常生气。",
            "现在请分析整个社交网络：\n"
            "a) Alice 和 Bob 的关系经历了哪 4 个阶段？转折点分别是什么？\n"
            "b) 第 4 轮的信息后来被证实是什么？谁传播的？\n"
            "c) 请识别出文中出现的三角关系结构",
        ],
        description="5人10对关系+传闻更正+三角关系（10 轮）：需要识别错误信息+关系结构分析",
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
            ["Alice", "Bob", "室友", "吵架", "和解", "澄清", "三角", "Bob", "Diana", "Eve"],
        ],
    ),

    # ══════════════════════════════════════════════════════════════
    # T4: 系统状态 — 10 指标 + 复合异常 + SLA 基线
    # ══════════════════════════════════════════════════════════════
    # 复杂度升级：
    #   1. 10 个监控指标并行追踪
    #   2. 出现"复合异常"（多个指标联动异常）
    #   3. 引入 SLA 基线概念，某些指标超基线算"违规"
    #   4. 第 6 轮一个指标出现"瞬态异常"（1 轮后就自愈）
    #   5. 最终问当前值 + 识别复合异常 + 统计 SLA 违规次数
    # ══════════════════════════════════════════════════════════════
    TestCase(
        id="T4",
        questions=[
            "【初始基线】服务器监控基线如下（SLA 红线），请逐项记住："
            "CPU=50%（红线 90%），内存=60%（红线 85%），"
            "磁盘已用 300GB/500GB（红线 90%），网络延迟=15ms（红线 100ms），"
            "QPS=1200（红线 8000），错误率=0.1%（红线 1%），"
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
            "最终所有指标趋于稳定。"
            "请回答：\n"
            "1）当前所有 10 个监控指标的值分别是什么？\n"
            "2）第 4 轮出现的复合异常涉及哪几个指标？\n"
            "3）瞬态异常发生在哪个指标？恢复方式是什么？\n"
            "4）SLA 红线被突破的总共次数（含瞬态）？",
        ],
        description="10指标+复合异常+SLA基线（10 轮）：复合异常识别+瞬态异常+SLA合规统计",
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
            ["60", "70", "350", "20", "3000", "0.2", "连接数", "CPU", "错误率", "延迟", "GC", "SLA", "7"],
        ],
        ground_truth="CPU=60% 内存=70% 磁盘=350GB 延迟=20ms QPS=3000 错误率=0.2%",
    ),

    # ══════════════════════════════════════════════════════════════
    # T5: 双轨时序因果推理 — 并行事件链 + 交叉影响
    # ══════════════════════════════════════════════════════════════
    # 复杂度升级：
    #   1. 两条并行事件链（A 链：数据库故障；B 链：网络攻击）
    #   2. 两条链在中间交叉影响（网络攻击导致备份也受损）
    #   3. 引入"非事件"（某件事本应发生但没发生）
    #   4. 最终问 5 道子题：A 链事件排序 / B 链关键节点 / 交叉点 / 非事件 / 总时长
    # ══════════════════════════════════════════════════════════════
    TestCase(
        id="T5",
        questions=[
            "【A 链 - 数据库故障】周一 8:00：主库复制延迟从 100ms 飙升到 30s，"
            "DBA 团队收到告警。",
            "【A 链】周一 10:00：排查发现是 binlog 文件磁盘空间满了，"
            "导致从库无法同步，需要紧急清理并扩容。",
            "【B 链 - 网络攻击】周一 14:00：安全团队发现异常流量模式，"
            "有外部 IP 正在对 API 网关发起 DDoS 攻击。",
            "【A 链】周一 16:00：清理磁盘 + 扩容完成，复制延迟恢复到 200ms。"
            "但 DBA 发现由于长时间同步延迟，有约 15 分钟的数据差异需要比对。",
            "【B 链】周一 18:00：WAF 规则已更新，DDoS 流量被拦截 90%，"
            "但攻击者开始变换 IP 和攻击向量。",
            "【交叉影响】周一 20:00：攻击者转向攻击备份系统，"
            "导致当天的自动备份失败。DBA 需要在数据比对的同时处理备份问题。",
            "【A 链延续】周二 02:00：数据差异比对完成，修复了 237 条不一致记录。",
            "【B 链延续】周二 06:00：安全团队部署了自动 IP 黑名单+速率限制，"
            "DDoS 攻击被完全遏制。",
            "【交叉修复】周二 10:00：备份系统恢复，开始补跑昨天的全量备份。"
            "原本计划周二的版本发布因故取消。",
            "【收尾】周二 18:00：全量备份完成，所有系统恢复正常。"
            "请精准回答：\n"
            "a) 数据库故障链（A 链）的完整时间线，从发现到修复的 4 个关键节点\n"
            "b) DDoS 攻击链（B 链）的关键节点\n"
            "c) 两条事件链在哪一点交叉影响的？\n"
            "d) 原计划周二的什么事件没有发生？\n"
            "e) 从第一次告警到完全恢复用了多长时间？",
        ],
        description="双轨并行+交叉影响+非事件识别（10 轮）：双链时序推理+交叉点+非事件",
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
    ),

    # ══════════════════════════════════════════════════════════════
    # T6: 跨 Session 长程记忆 — 4 Session + 诱导性问题
    # ══════════════════════════════════════════════════════════════
    # 复杂度升级：
    #   1. Session 1（Q1-3）：项目 Alpha 技术方案
    #   2. Session 2（Q4-6）：项目 Beta 完全不同技术栈（干扰）
    #   3. Session 3（Q7-9）：旅行计划（强干扰，有数字重叠）
    #   4. Session 4（Q10-15）：回到 Alpha + Beta 对比 + 诱导测试
    #   5. 诱导性问题：故意问"项目 Alpha 用了什么数据库？MySQL 还是 PostgreSQL？"
    #      正确答案是 PostgreSQL，但 Beta 用了 MySQL，旅行也提到了日期数字
    #   6. 最终问：Alpha 完整方案 + Beta 方案对比 + 识别诱导
    # ══════════════════════════════════════════════════════════════
    TestCase(
        id="T6",
        questions=[
            "【Session 1 - 项目 Alpha】经过讨论，Alpha 技术栈确定："
            "前端 React 18 + TypeScript，后端 Go + Gin，数据库 PostgreSQL 15，"
            "缓存 Redis 7，消息队列 RabbitMQ。",
            "PostgreSQL 选型原因：需要 PostGIS 地理空间查询 + 高并发写入（5000 QPS），"
            "MVCC 机制更适合我们的读写比例（7:3）。",
            "部署方案：Docker + Kubernetes，3 副本自动扩缩容，"
            "目标可用性 99.9%，API 采用 REST + JWT + Swagger。",
            "【Session 2 - 项目 Beta，完全不同】新项目 Beta 启动，技术栈完全不同："
            "前端 Vue 3 + JavaScript，后端 Python FastAPI，"
            "数据库 MySQL 8.0，缓存 Memcached，消息队列 Kafka。",
            "MySQL 选型原因：Beta 项目是内容管理系统，主要是 CRUD 操作，"
            "MySQL 的 InnoDB 引擎对事务支持好，且运维团队更熟悉。",
            "Beta 部署方案：单机 Docker Compose，2 副本，目标可用性 99.5%，"
            "API 采用 GraphQL + API Key 认证 + 手写文档。",
            "【Session 3 - 旅行计划，数字干扰】我计划明年去日本旅行，"
            "总预算 15000 元，12 月 15 日出发，12 月 22 日回。",
            "住宿 Airbnb 每晚 500 元，一共 7 晚，行程东京 3 天→京都 2 天→大阪 2 天。",
            "【Session 3 细节】JR Pass 7 天通票，买了旅游保险 300 元。"
            "信用卡额度 50000 元，准备带 5000 元现金。",
            "【Session 4 - 回到 Alpha + Beta 对比】好的，现在我们同时推进 Alpha 和 Beta。"
            "先问 Alpha：前端用的什么框架？",
            "Alpha 的数据库选型是 MySQL 还是 PostgreSQL？选它的两个原因是什么？"
            "（注意：Beta 用的数据库不同，别搞混了）",
            "Beta 的 API 认证方式和 Alpha 有什么不同？两个项目的部署架构区别是什么？",
            "Alpha 的消息队列选了什么？Beta 的呢？",
            "旅行计划的出发日期是哪一天？（和项目无关，只是想确认记忆是否有交叉污染）",
            "请综合对比 Alpha 和 Beta 两个项目的完整技术方案差异："
            "技术栈、数据库及原因、部署架构、可用性目标、API 风格。"
            "最后说明：旅行计划的日期是否被错误地混入了项目记忆中？",
        ],
        description="4 Session+诱导性提问（15 轮）：跨 Session检索+干扰排除+交叉对比+诱导识别",
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
            ["React", "Go", "PostgreSQL", "Redis", "RabbitMQ", "Vue", "Python", "MySQL", "Memcached", "Kafka", "12 月 15"],
        ],
        ground_truth="React+Go+PostgreSQL+Redis+RabbitMQ  vs  Vue+Python+MySQL+Memcached+Kafka",
    ),
]


async def run_comparison(llm_client: Any, db_path: Optional[str] = None):
    """运行对比测试。"""

    # ── 初始化两个 Agent ──
    simple = SimpleAgent(llm_client)
    memory = MemoryAgent(llm_client, db_path)

    # ── 对比报告 ──
    report_lines = [
        "=" * 80,
        "  记忆系统对比测试报告",
        "=" * 80,
        f"  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  LLM: {type(llm_client).__name__}",
        "-" * 80,
    ]

    all_results = []

    for case in TEST_CASES:
        print(f"\n{'=' * 60}")
        print(f"  测试用例: {case.id} — {case.description}")
        print(f"{'=' * 60}")

        case_lines = [
            f"\n{'─' * 70}",
            f"  测试用例 {case.id}: {case.description}",
            f"{'─' * 70}",
        ]

        case_results = {"id": case.id, "description": case.description, "rounds": []}
        total_quality_a = 0.0
        total_quality_b = 0.0
        recall_rounds = 0  # 实际有记忆召回需求的轮次数

        # 逐个问题测试
        last_q_idx = len(case.questions) - 1
        for q_idx, question in enumerate(case.questions):
            print(f"\n  Q{q_idx+1}: {question[:80]}...")

            # Agent A — 无记忆
            t0 = time.time()
            resp_a = await simple.chat(question)
            latency_a = (time.time() - t0) * 1000

            # Agent B — 有记忆
            t0 = time.time()
            resp_b = await memory.chat(question)
            latency_b = (time.time() - t0) * 1000

            # ── 评估 1: 记忆召回率 ──
            expected = case.expected_keywords_per_q[q_idx]
            question_lower = question.lower() if question else ""

            # 只保留"记忆关键词"：不在当前问题文本中的词才需要从历史回忆
            memory_kw = [kw for kw in expected if kw.lower() not in question_lower]

            # 第一轮无历史可回忆；如果过滤后无关键词，该轮也不计分
            skip_recall = (q_idx == 0) or (not memory_kw)

            if skip_recall:
                quality_a = quality_b = None
            else:
                hits_a = sum(1 for kw in memory_kw if kw.lower() in str(resp_a).lower())
                hits_b = sum(1 for kw in memory_kw if kw.lower() in str(resp_b).lower())
                quality_a = hits_a / len(memory_kw) if memory_kw else 0
                quality_b = hits_b / len(memory_kw) if memory_kw else 0
                total_quality_a += quality_a
                total_quality_b += quality_b
                recall_rounds += 1

            # 全部关键词命中（含问题和历史）——仅供对比参照
            all_kw_hits_a = sum(1 for kw in expected if kw.lower() in str(resp_a).lower())
            all_kw_hits_b = sum(1 for kw in expected if kw.lower() in str(resp_b).lower())

            # ── 评估 2: 最后一问的精确匹配 ──
            exact_a = exact_b = None
            if q_idx == last_q_idx and case.ground_truth:
                exact_a = _exact_match(str(resp_a), case.ground_truth)
                exact_b = _exact_match(str(resp_b), case.ground_truth)

            round_info = {
                "question": question[:60],
                "latency_a_ms": round(latency_a, 0),
                "latency_b_ms": round(latency_b, 0),
                "all_kw_hits_a": all_kw_hits_a,
                "all_kw_hits_b": all_kw_hits_b,
            }
            if quality_a is not None:
                round_info["quality_a"] = round(quality_a, 2)
                round_info["quality_b"] = round(quality_b, 2)
                round_info["memory_kw_total"] = len(memory_kw)
                round_info["memory_kw_hits_a"] = hits_a
                round_info["memory_kw_hits_b"] = hits_b
            if exact_a is not None:
                round_info["exact_a"] = exact_a
                round_info["exact_b"] = exact_b
            case_results["rounds"].append(round_info)

            # 输出
            if skip_recall and q_idx == 0:
                print(f"    ┌─ [无记忆] ⏭️ 第 1 轮跳过（无历史可回忆）  ({latency_a:.0f}ms)")
                print(f"    │  回复片段: {str(resp_a)[:150]}")
                print(f"    └─ [有记忆] ⏭️ 第 1 轮跳过（无历史可回忆）  ({latency_b:.0f}ms)")
                print(f"       回复片段: {str(resp_b)[:150]}")
            elif skip_recall:
                excluded = len(expected) - len(memory_kw)
                print(f"    ┌─ [无记忆] ⏭️ 所有关键词均出自本轮问题（{excluded} 个），无需回忆  ({latency_a:.0f}ms)")
                print(f"    └─ [有记忆] ⏭️ 同样跳过  ({latency_b:.0f}ms)")
            else:
                excluded = len(expected) - len(memory_kw)
                kw_info = f"记忆召回: {hits_a}/{len(memory_kw)} (问题自带 {excluded} 个已过滤)"
                print(f"    ┌─ [无记忆] {kw_info}  质量: {quality_a:.0%}  ({latency_a:.0f}ms)")
                if exact_a is not None:
                    print(f"    │  精确匹配: {'✅ 正确' if exact_a else '❌ 错误'} (期望: {case.ground_truth})")
                print(f"    │  回复片段: {str(resp_a)[:150]}")

                kw_info = f"记忆召回: {hits_b}/{len(memory_kw)} (问题自带 {excluded} 个已过滤)"
                print(f"    └─ [有记忆] {kw_info}  质量: {quality_b:.0%}  ({latency_b:.0f}ms)")
                if exact_b is not None:
                    print(f"    │  精确匹配: {'✅ 正确' if exact_b else '❌ 错误'} (期望: {case.ground_truth})")
                print(f"       回复片段: {str(resp_b)[:150]}")

                if quality_b is not None and quality_a is not None:
                    if q_idx == last_q_idx:
                        if exact_a is not None and exact_b is not None:
                            if exact_b and not exact_a:
                                print(f"      🎯 记忆系统生效: 无记忆回答错误，有记忆正确！")
                            elif exact_a and not exact_b:
                                print(f"      ⚠️ 无记忆回答正确，有记忆反而错误（记忆检索可能有问题）")
                            elif exact_a and exact_b:
                                print(f"      ➖ 两者都正确（LLM 从问题推断出答案）")
                            else:
                                print(f"      ❌ 两者都错误（记忆检索没找到关键信息）")
                    elif q_idx >= 1:
                        if quality_b > quality_a:
                            print(f"      ✅ 记忆系统生效: 召回质量提升 +{quality_b - quality_a:.0%}")
                        elif quality_a > quality_b:
                            print(f"      ⚠️ SimpleAgent 反而更好: 质量差距 -{quality_a - quality_b:.0%}")

        # 用例汇总
        avg_a = total_quality_a / recall_rounds if recall_rounds > 0 else 0
        avg_b = total_quality_b / recall_rounds if recall_rounds > 0 else 0
        case_results["avg_quality_a"] = round(avg_a, 2)
        case_results["avg_quality_b"] = round(avg_b, 2)
        case_results["improvement"] = round(avg_b - avg_a, 2)
        case_results["recall_rounds"] = recall_rounds
        all_results.append(case_results)

        case_lines.append(
            f"  记忆召回率（共 {recall_rounds} 轮有效测试）"
            f" — 无记忆: {avg_a:.1%}  |  有记忆: {avg_b:.1%}"
        )
        improvement = avg_b - avg_a
        if improvement > 0.15:
            case_lines.append(f"  效果: 记忆系统显著提升 (Δ={improvement:.0%})")
        elif improvement > 0:
            case_lines.append(f"  效果: 记忆系统略有提升 (Δ={improvement:.0%})")
        else:
            case_lines.append(f"  效果: 记忆系统效果不明显")
        report_lines.extend(case_lines)

    # ── 总报告 ──
    report_lines.extend([
        f"\n{'=' * 70}",
        "  总体结论",
        f"{'=' * 70}",
    ])

    total_weight = sum(r["recall_rounds"] for r in all_results)
    total_avg_a = sum(r["avg_quality_a"] * r["recall_rounds"] for r in all_results) / total_weight if total_weight > 0 else 0
    total_avg_b = sum(r["avg_quality_b"] * r["recall_rounds"] for r in all_results) / total_weight if total_weight > 0 else 0
    total_improv = total_avg_b - total_avg_a

    report_lines.append(f"  ┌─ {'场景':10s} │ {'无记忆(召回)':16s} │ {'有记忆(召回)':16s} │ {'无记忆(精确)':14s} │ {'有记忆(精确)':14s} │")
    report_lines.append(f"  ├─{'─'*12}┼{'─'*18}┼{'─'*18}┼{'─'*16}┼{'─'*16}┤")
    for r in all_results:
        last = r["rounds"][-1]
        exact_a = "—" if "exact_a" not in last else ("✅" if last["exact_a"] else "❌")
        exact_b = "—" if "exact_b" not in last else ("✅" if last["exact_b"] else "❌")
        report_lines.append(
            f"  │ {r['id']:10s} │  {r['avg_quality_a']:.0%}             │  {r['avg_quality_b']:.0%}             │  {exact_a:>12s}     │  {exact_b:>12s}     │"
        )
    report_lines.append(f"  └─{'─'*12}┴{'─'*18}┴{'─'*18}┴{'─'*16}┴{'─'*16}┘")

    report_lines.append(f"")
    report_lines.append(f"  全部测试平均记忆召回率（已排除问题自带关键词）:")
    report_lines.append(f"    无记忆系统: {total_avg_a:.1%}")
    report_lines.append(f"    有记忆系统: {total_avg_b:.1%}")
    report_lines.append(f"    提升幅度:   {total_improv:.1%}")

    # 统计精确匹配胜出次数
    wins = sum(1 for r in all_results for last in [r["rounds"][-1]] if last.get("exact_b") and not last.get("exact_a"))
    losses = sum(1 for r in all_results for last in [r["rounds"][-1]] if last.get("exact_a") and not last.get("exact_b"))
    ties = sum(1 for r in all_results for last in [r["rounds"][-1]] if last.get("exact_a") is not None and last.get("exact_a") == last.get("exact_b"))

    if wins > losses:
        report_lines.append(f"")
        report_lines.append(f"  精确匹配胜负: 记忆系统 {wins} 胜 / {losses} 负 / {ties} 平")
        report_lines.append(f"  ✅ 结论: 记忆系统有效 — 精确匹配胜出 + 召回率提升 {total_improv:.1%}")
    elif total_improv > 0.10:
        report_lines.append(f"")
        report_lines.append(f"  ✅ 结论: 记忆系统有效 — 记忆召回率显著提升 {total_improv:.1%}")
        if wins + losses + ties > 0:
            report_lines.append(f"  精确匹配: {wins} 胜 / {losses} 负 / {ties} 平")
    elif total_improv < -0.05 or losses > wins:
        report_lines.append(f"  ⚠️ 结论: 记忆系统表现需优化 — 无记忆在某些场景反而更好 (Δ={total_improv:.1%})")
    elif total_improv > 0:
        report_lines.append(f"")
        report_lines.append(f"  📈 结论: 记忆系统略有提升 — 召回率 +{total_improv:.1%}")
    else:
        report_lines.append(f"  ➖ 结论: 当前场景下记忆系统效果不显著")

    report_lines.append(f"\n{'=' * 80}")

    # 输出报告
    report = "\n".join(report_lines)
    print(f"\n{report}")

    # 保存报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"memory_comparison_report_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n详细报告已保存: {report_path}")

    await memory.close()


# ═══════════════════════════════════════════════════════════════════
# 精确匹配工具
# ═══════════════════════════════════════════════════════════════════

def _exact_match(response: str, ground_truth: str) -> bool:
    """精确匹配最后一问的答案。

    支持多种匹配模式:
    - "用逗号/空格分隔的多值": 检查所有值是否都出现在回复中
      (例如 "Alice=7101, Bob=18201, Charlie=1800" → 三个等式都需匹配)
    - "用加号拼接的关键要素": 检查每个要素是否都出现在回复中
      (例如 "React+Go+PostgreSQL" → React、Go、PostgreSQL 都需出现)
    """
    resp_lower = response.lower()

    # 模式 1: 逗号/分号分隔的多值等式 → 每个 key=value 都需匹配
    if "=" in ground_truth:
        parts = [p.strip() for p in ground_truth.replace(";", ",").split(",")]
        if len(parts) > 1:
            return all(p.lower() in resp_lower for p in parts if p)

    # 模式 2: 加号拼接的关键要素列表 → 每个要素都需出现
    if "+" in ground_truth:
        items = [item.strip() for item in ground_truth.split("+")]
        if len(items) > 1:
            return all(item.lower() in resp_lower for item in items if item)

    # 模式 3: 单值（兼容旧版）
    gt_lower = ground_truth.lower()
    return gt_lower in resp_lower


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os

    # 自动检测可用的 LLM（默认使用 DeepSeek）
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    db_path = os.environ.get("DATABASE_URL")

    if provider == "deepseek" or os.environ.get("DEEPSEEK_API_KEY"):
        from context_os.llm.deepseek_client import DeepSeekClient
        llm = DeepSeekClient()
        print("使用 LLM: DeepSeek")
    elif provider == "anthropic" or os.environ.get("ANTHROPIC_API_KEY"):
        from context_os.llm.anthropic_client import AnthropicClient
        llm = AnthropicClient()
        print("使用 LLM: Anthropic Claude")
    elif provider == "openai" or os.environ.get("OPENAI_API_KEY"):
        from context_os.llm.openai_client import OpenAIClient
        llm = OpenAIClient()
        print("使用 LLM: OpenAI")
    else:
        print("错误: 未检测到 API Key。请设置 DEEPSEEK_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY")
        print("或运行: $env:DEEPSEEK_API_KEY='sk-xxx'; python examples/memory_comparison.py")
        exit(1)

    if not db_path:
        print("提示: DATABASE_URL 未设置，记忆将使用 JSON 文件降级存储")
        print("     设置后记忆可持久化: $env:DATABASE_URL='./data/context_os.db'")
        print()

    asyncio.run(run_comparison(llm, db_path))
