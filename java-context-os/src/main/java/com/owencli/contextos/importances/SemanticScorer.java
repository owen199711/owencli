package com.owencli.contextos.importances;

import com.owencli.contextos.core.base.BaseLLMClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;

/**
 * Semantic Scorer — uses a lightweight LLM call to judge long-term memory value.
 * <p>
 * Prompt:
 * <pre>
 * You are Memory Importance Judge.
 * Score: 0~1
 * Should this memory be useful after 30 days?
 * Return only score.
 * </pre>
 * Cost is minimal (1 token output) but gives vastly better semantic understanding
 * than keyword rules. Weight in final score: 0.35.
 */
public class SemanticScorer {

    private static final Logger log = LoggerFactory.getLogger(SemanticScorer.class);

    private final BaseLLMClient llmClient;

    public SemanticScorer(BaseLLMClient llmClient) {
        this.llmClient = llmClient;
    }

    /**
     * Rate the long-term value of a piece of content.
     *
     * @return semantic importance score 0.0~1.0
     */
    public CompletableFuture<Double> score(String content) {
        if (content == null || content.isBlank()) {
            return CompletableFuture.completedFuture(0.0);
        }

        String prompt = String.format(
                "You are Memory Importance Judge.\n\n" +
                        "Score: 0~1\n" +
                        "Should this memory be useful after 30 days?\n" +
                        "Return only a single number (0.0 ~ 1.0).\n\n" +
                        "Memory: %s",
                content.length() > 200 ? content.substring(0, 200) : content
        );

        return llmClient.complete(prompt)
                .thenApply(response -> parseScore(String.valueOf(response)))
                .exceptionally(e -> {
                    log.warn("SemanticScorer LLM failed ({}), using fallback 0.5", e.getMessage());
                    return 0.5;
                });
    }

    private double parseScore(String text) {
        if (text == null || text.isBlank()) return 0.5;
        try {
            // Extract first number found in response
            var matcher = java.util.regex.Pattern.compile("(\\d+\\.?\\d*)").matcher(text.trim());
            if (matcher.find()) {
                double score = Double.parseDouble(matcher.group(1));
                return Math.min(1.0, Math.max(0.0, score));
            }
        } catch (Exception ignored) {}
        return 0.5;
    }
}
