package com.owencli.contextos.core.base;

import java.util.concurrent.CompletableFuture;

/**
 * Base class for LLM API clients.
 */
public interface BaseLLMClient {

    CompletableFuture<Object> complete(String prompt, String system, int maxTokens,
                                       double temperature, String responseFormat);

    default CompletableFuture<Object> complete(String prompt) {
        return complete(prompt, null, 4096, 0.7, null);
    }

    default CompletableFuture<Object> complete(String prompt, int maxTokens) {
        return complete(prompt, null, maxTokens, 0.7, null);
    }
}
