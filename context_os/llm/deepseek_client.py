"""DeepSeek LLM 客户端（OpenAI 兼容接口）。"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from openai import AsyncOpenAI

from context_os.core.logger import get_logger
from context_os.llm.client import BaseLLMClient

logger = get_logger(__name__)


class DeepSeekClient(BaseLLMClient):
    """DeepSeek API 客户端。

    使用 OpenAI 兼容接口对接 DeepSeek。

    Args:
        api_key: API 密钥，默认从 DEEPSEEK_API_KEY 环境变量读取。
        model: 模型名称，默认 deepseek-chat。
        base_url: API 地址，默认 https://api.deepseek.com/v1。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com/v1",
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            logger.warning("DEEPSEEK_API_KEY not set")
        self.model = model
        self.base_url = base_url
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        logger.info("DeepSeekClient initialized: model=%s, base_url=%s", model, base_url)

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        response_format: Optional[str] = None,
    ) -> str | dict[str, Any]:
        """发送请求到 DeepSeek。

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
            "DeepSeek request: model=%s, max_tokens=%d",
            self.model, max_tokens,
        )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content or ""

            logger.debug(
                "DeepSeek response: finish_reason=%s, tokens=%d/%d",
                response.choices[0].finish_reason,
                response.usage.prompt_tokens if response.usage else 0,
                response.usage.completion_tokens if response.usage else 0,
            )

            if response_format == "json":
                return json.loads(text)
            return text

        except Exception as e:
            logger.error("DeepSeek API error: %s", e, exc_info=True)
            raise
