package com.owencli.contextos.llm;

import com.owencli.contextos.core.base.BaseLLMClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;

/**
 * Mock LLM client — 无需 API Key，返回模拟回复。
 * 用于在无 API Key 环境下测试记忆系统和 Pipeline 流程。
 */
public class MockClient implements BaseLLMClient {

    private static final Logger log = LoggerFactory.getLogger(MockClient.class);

    @Override
    public CompletableFuture<Object> complete(String prompt, String system, int maxTokens,
                                              double temperature, String responseFormat) {
        return CompletableFuture.supplyAsync(() -> {
            log.debug("MockClient received prompt ({} chars)", prompt.length());
            String response = "[模拟回复] 已收到您的请求，内容长度 " + prompt.length() + " 字符。";
            if ("json".equals(responseFormat)) {
                return "{\"response\": \"模拟回复\", \"length\": " + prompt.length() + "}";
            }
            return response;
        });
    }
}
