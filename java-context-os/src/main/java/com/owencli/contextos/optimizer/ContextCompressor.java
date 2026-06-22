package com.owencli.contextos.optimizer;

import com.owencli.contextos.core.base.BaseLLMClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.CompletableFuture;

/**
 * Context compressor — compresses conversation history using LLM summarization.
 */
public class ContextCompressor {

    private static final Logger log = LoggerFactory.getLogger(ContextCompressor.class);
    private static final String COMPRESS_PROMPT = """
            Compress the following conversation history into a concise summary.
            Keep all important facts, decisions, and user preferences.
            
            Conversation:
            {history}
            
            Compressed summary:
            """;

    private final BaseLLMClient llmClient;

    public ContextCompressor() {
        this(null);
    }

    public ContextCompressor(BaseLLMClient llmClient) {
        this.llmClient = llmClient;
    }

    public CompletableFuture<String> compressConversation(List<String> turns, int maxTokens) {
        if (llmClient == null) {
            log.debug("No LLM client, using simple truncation");
            return CompletableFuture.completedFuture(truncateTurns(turns, maxTokens));
        }

        String history = String.join("\n", turns);
        if (history.length() < maxTokens * 2) {
            return CompletableFuture.completedFuture(history);
        }

        String prompt = COMPRESS_PROMPT.replace("{history}", history);
        return llmClient.complete(prompt, null, maxTokens / 2, 0.5, null)
                .thenApply(Object::toString)
                .exceptionally(e -> {
                    log.warn("Compression failed, fallback to truncation: {}", e.getMessage());
                    return truncateTurns(turns, maxTokens);
                });
    }

    private String truncateTurns(List<String> turns, int maxTokens) {
        var sb = new StringBuilder();
        int estimatedTokens = 0;
        for (String turn : turns) {
            int tokens = turn.length() / 4 + 1;
            if (estimatedTokens + tokens > maxTokens) break;
            sb.append(turn).append("\n");
            estimatedTokens += tokens;
        }
        return sb.toString();
    }
}
