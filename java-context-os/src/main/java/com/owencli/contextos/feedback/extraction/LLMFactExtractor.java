package com.owencli.contextos.feedback.extraction;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;

/**
 * LLM-based fact extractor — fallback when rule engine cannot match.
 * <p>
 * Uses a structured prompt to extract stable facts from any text.
 * Handles complex patterns like "其实同事都喜欢叫我老王" which rules cannot cover.
 */
public class LLMFactExtractor {

    private static final Logger log = LoggerFactory.getLogger(LLMFactExtractor.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final BaseLLMClient llmClient;

    public LLMFactExtractor(BaseLLMClient llmClient) {
        this.llmClient = llmClient;
        log.info("LLMFactExtractor initialized");
    }

    public CompletableFuture<List<RuleFactExtractor.CandidateFact>> extract(String input) {
        if (input == null || input.isBlank()) {
            return CompletableFuture.completedFuture(List.of());
        }

        String prompt = String.format(
                "Extract stable, long-term user facts from the following text.\n\n" +
                        "RULES:\n" +
                        "1. Only extract factual, stable information\n" +
                        "2. Do NOT extract temporary states (tired, hungry, today, etc.)\n" +
                        "3. Do NOT extract conversation topics or questions\n" +
                        "4. For name changes: the LATEST name is the fact\n" +
                        "5. For preferences: extract the preference, not the action\n\n" +
                        "Respond ONLY with a JSON array, no other text:\n" +
                        "[{\"type\": \"user.name\", \"value\": \"李四\", \"confidence\": 0.95}]\n\n" +
                        "Text: %s", input);

        return llmClient.complete(prompt)
                .thenApply(response -> {
                    String text = String.valueOf(response).trim();
                    return parseResponse(text);
                })
                .exceptionally(e -> {
                    log.warn("LLM fact extraction failed: {}", e.getMessage());
                    return List.of();
                });
    }

    @SuppressWarnings("unchecked")
    private List<RuleFactExtractor.CandidateFact> parseResponse(String text) {
        try {
            // Extract JSON array from response
            int start = text.indexOf('[');
            int end = text.lastIndexOf(']');
            if (start < 0 || end < 0) return List.of();

            String json = text.substring(start, end + 1);
            var list = MAPPER.readValue(json, List.class);
            var results = new ArrayList<RuleFactExtractor.CandidateFact>();

            for (var item : list) {
                if (item instanceof Map m) {
                    String type = (String) m.getOrDefault("type", "");
                    String value = (String) m.getOrDefault("value", "");
                    double confidence = toDouble(m.getOrDefault("confidence", 0.7));
                    if (!type.isEmpty() && !value.isEmpty()) {
                        results.add(new RuleFactExtractor.CandidateFact(
                                type, value, Math.min(1.0, confidence),
                                "llm", 20  // LLM has lower priority than rules
                        ));
                    }
                }
            }
            return results;
        } catch (Exception e) {
            log.warn("Failed to parse LLM fact extraction response: {}", e.getMessage());
            return List.of();
        }
    }

    private double toDouble(Object obj) {
        if (obj instanceof Number n) return n.doubleValue();
        try { return Double.parseDouble(obj.toString()); }
        catch (Exception e) { return 0.7; }
    }
}
