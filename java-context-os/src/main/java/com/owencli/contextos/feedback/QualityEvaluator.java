package com.owencli.contextos.feedback;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.model.EvalMetrics;
import com.owencli.contextos.core.model.PackagedContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.CompletableFuture;

public class QualityEvaluator {
    private static final Logger log = LoggerFactory.getLogger(QualityEvaluator.class);
    private static final List<String> ERROR_SIGNALS = List.of("error","unable to","cannot","failed","apologies");

    private final BaseLLMClient llmClient;

    public QualityEvaluator() { this(null); }
    public QualityEvaluator(BaseLLMClient llmClient) { this.llmClient = llmClient; }

    public CompletableFuture<EvalMetrics> evaluate(PackagedContext packed, String llmResponse,
                                                   double latencyMs, int tokenCount) {
        boolean success = checkSuccess(llmResponse);
        double cost = tokenCount * 3.0 / 1_000_000;
        CompletableFuture<Double> qualityFuture = (llmClient != null && success)
                ? rateQuality(packed.getRawPrompt(), llmResponse)
                : CompletableFuture.completedFuture(success ? 0.8 : 0.1);
        return qualityFuture.thenApply(quality -> {
            var m = new EvalMetrics();
            m.setAnswerQuality(Math.round(quality * 1000.0) / 1000.0);
            m.setLatencyMs(Math.round(latencyMs * 10.0) / 10.0);
            m.setCostUsd(Math.round(cost * 1_000_000.0) / 1_000_000.0);
            m.setSuccess(success);
            m.setRewardScore(Math.round((quality * (success ? 0.8 : 0.2)) * 1000.0) / 1000.0);
            return m;
        });
    }

    private static boolean checkSuccess(String r) {
        if (r == null) return false;
        String s = r.length() > 200 ? r.substring(0, 200).toLowerCase() : r.toLowerCase();
        return ERROR_SIGNALS.stream().noneMatch(s::contains);
    }

    private CompletableFuture<Double> rateQuality(String prompt, String response) {
        String eval = "Rate the following AI response on a scale of 0.0 to 1.0.\n" +
                "Consider: accuracy, completeness, clarity, helpfulness.\n" +
                "Return ONLY a number between 0 and 1.\n\nResponse: " +
                (response.length() > 2000 ? response.substring(0, 2000) : response);
        return llmClient.complete(eval, null, 50, 0.3, null)
                .thenApply(r -> { try { return Math.max(0, Math.min(1.0, Double.parseDouble(r.toString().trim()))); } catch (Exception e) { return 0.5; }})
                .exceptionally(e -> 0.5);
    }
}
