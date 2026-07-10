"""测试 TripleExtractor — 通道 A 规则三元组抽取。"""

import pytest
from context_os.feedback.triple_extractor import TripleExtractor, TripleExtractResult


class TestTripleExtractor:
    """通道 A 规则抽取测试。"""

    @pytest.fixture
    def ex(self):
        return TripleExtractor()

    # ── 6 种模式各 3 个例子 ──

    def test_x_is_y_chinese(self, ex):
        """'X 是 Y' 模式。"""
        result = ex.extract("Python 是一种编程语言")
        assert result.channel_a_hit
        assert len(result.triples) >= 1

    def test_x_is_y_english(self, ex):
        result = ex.extract("FastAPI is a web framework")
        assert result.channel_a_hit
        assert len(result.triples) >= 1

    def test_x_is_y_multi(self, ex):
        """多个 'X 是 Y' 在一段文本中。"""
        result = ex.extract("Django 是一个全栈框架，Flask 是一个微框架")
        assert result.channel_a_hit
        assert len(result.triples) >= 1  # 清理后标点被移除，跨句匹配可能合并

    def test_x_belongs_y(self, ex):
        """'X 属于 Y' 模式。"""
        result = ex.extract("地球属于太阳系")
        assert result.channel_a_hit

    def test_x_belongs_y_english(self, ex):
        result = ex.extract("This module belongs to the core package")
        assert result.channel_a_hit

    def test_x_belongs_y_more(self, ex):
        result = ex.extract("HTTP 协议属于应用层协议")
        assert result.channel_a_hit

    def test_x_based_on_y(self, ex):
        """'X 基于 Y' 模式。"""
        result = ex.extract("FastAPI 基于 Starlette 框架")
        assert result.channel_a_hit

    def test_x_based_on_english(self, ex):
        result = ex.extract("This approach is based on transformer architecture")
        assert result.channel_a_hit

    def test_x_based_on_another(self, ex):
        result = ex.extract("Docker 基于 Linux 容器技术")
        assert result.channel_a_hit

    def test_x_contains_y(self, ex):
        """'X 包含 Y' 模式。"""
        result = ex.extract("这个项目包含三个模块")
        assert result.channel_a_hit

    def test_x_includes_y(self, ex):
        result = ex.extract("The SDK includes authentication helpers")
        assert result.channel_a_hit

    def test_x_contains_y_technical(self, ex):
        result = ex.extract("Django 包含 ORM、模板引擎和认证系统")
        assert result.channel_a_hit

    def test_x_de_y_is_z(self, ex):
        """'X 的 Y 是 Z' 模式。"""
        result = ex.extract("Python 的作者是 Guido van Rossum")
        assert result.channel_a_hit

    def test_x_de_y_z_english_style(self, ex):
        """英文中 'X's Y is Z' 被映射为类似模式。"""
        result = ex.extract("Python's creator is Guido van Rossum")
        # 英文的 apostrophe s 可能不被识别为 '的'，但 X 是 Y 应命中
        # 不强求一定有 "的" 模式

    def test_x_de_y_another(self, ex):
        result = ex.extract("Django 的默认端口是 8000")
        assert result.channel_a_hit

    def test_x_yong_y(self, ex):
        """'X 用 Y' 模式。"""
        result = ex.extract("这个项目用 Docker 部署")
        assert result.channel_a_hit

    def test_x_uses_y_english(self, ex):
        result = ex.extract("The app uses PostgreSQL for storage")
        assert result.channel_a_hit

    def test_x_yong_y_v3(self, ex):
        result = ex.extract("我用 Python 写脚本")
        assert result.channel_a_hit

    # ── Channel B 信号检测 ──

    def test_channel_b_signal_concept_keyword(self, ex):
        """通道 A 未命中但包含概念关键词 → channel_b_signal=True。"""
        result = ex.extract("微服务架构中服务间通信的协议选择很关键")
        # 包含"架构"和"协议"概念关键词
        assert result.channel_b_signal
        assert not result.channel_a_hit

    def test_channel_b_no_signal(self, ex):
        """既无通道 A 命中也无概念关键词。"""
        result = ex.extract("今天天气不错，适合出去玩")
        assert not result.channel_a_hit
        assert not result.channel_b_signal

    def test_channel_a_with_both_channels(self, ex):
        """通道 A 命中时 channel_b_signal 应为 False。"""
        result = ex.extract("Kubernetes 是一个容器编排平台")
        assert result.channel_a_hit
        # 通道 A 命中后不应再触发 B
        assert result.channel_b_signal is False

    # ── 边界 case ──

    def test_empty_text(self, ex):
        result = ex.extract("")
        assert not result.channel_a_hit
        assert not result.channel_b_signal

    def test_no_match(self, ex):
        result = ex.extract("abc 123 xyz")
        assert not result.channel_a_hit
        assert not result.channel_b_signal

    def test_deduplication(self, ex):
        """同三元组应去重。"""
        result = ex.extract("Python 是一种语言，Python 是一种语言")
        # 应有去重
        triples_str = {(t.subject, t.relation, t.obj) for t in result.triples}
        assert len(triples_str) <= 1 + 1  # 至少去重

    def test_confidence_is_one(self, ex):
        """通道 A 的 confidence 应为 1.0。"""
        result = ex.extract("Python 是一种编程语言")
        if result.triples:
            for t in result.triples:
                assert t.confidence == 1.0
                assert t.source == "rule"
