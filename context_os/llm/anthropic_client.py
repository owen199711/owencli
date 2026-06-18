"""Anthropic Claude LLM 客户端实现。"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from anthropic import AsyncAnthropic

from context_os.core.logger import get_logger
from context_os.llm.client import BaseLLMClient

logger = get_logger(__name__)


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API 客户端。

    Args:
        api_key: API 密钥，默认从 ANTHROPIC_API_KEY 环境变量读取。
        model: 模型名称，默认 claude-sonnet-4-20250514。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set")
        self.model = model
        self._client = AsyncAnthropic(api_key=self.api_key)
        logger.info("AnthropicClient initialized: model=%s", model)

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        response_format: Optional[str] = None,
    ) -> str | dict[str, Any]:
        """发送请求到 Claude。

        Args:
            prompt: 用户 prompt。
            system: 系统指令。
            max_tokens: 最大输出 token 数。
            temperature: 温度参数。
            response_format: "json" 或 None。

        Returns:
            字符串或解析后的 JSON 字典。
        """
        logger.debug(
            "Claude request: model=%s, max_tokens=%d, system=%s",
            self.model, max_tokens, bool(system),
        )

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        try:
            response = await self._client.messages.create(**kwargs)
            text = response.content[0].text

            logger.debug(
                "Claude response: stop_reason=%s, input_tokens=%d, output_tokens=%d",
                response.stop_reason,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )

            if response_format == "json":
                return json.loads(text)
            return text

        except Exception as e:
            logger.error("Claude API error: %s", e, exc_info=True)
            raise
