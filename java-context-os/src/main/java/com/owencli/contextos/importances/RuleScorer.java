package com.owencli.contextos.importances;

import com.owencli.contextos.feedback.MemoryExtractor.ExtractedContent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Rule Scorer — evaluates memory importance using deterministic rules.
 * <p>
 * This is the existing {@code ImportanceScorer} logic factored out as one dimension.
 * Covers: success, input length, entity count, technical keywords, error keywords.
 * Weight in final score: 0.20.
 */
public class RuleScorer {

    private static final Logger log = LoggerFactory.getLogger(RuleScorer.class);

    public double score(ExtractedContent extracted) {
        double score = 0.0;

        // Factor 1: Task success
        if (extracted.isSuccess()) score += 0.2;

        // Factor 2: Input length
        int inputLen = extracted.getInput() != null ? extracted.getInput().length() : 0;
        if (inputLen > 100) score += 0.25;
        else if (inputLen > 50) score += 0.15;
        else if (inputLen > 20) score += 0.05;

        // Factor 3: Key concepts/entities
        int conceptCount = extracted.getKeyConcepts() != null ? extracted.getKeyConcepts().size() : 0;
        if (conceptCount >= 3) score += 0.30;
        else if (conceptCount >= 1) score += 0.15;

        // Factor 4: Technical/coding keywords
        String input = extracted.getInput() != null ? extracted.getInput() : "";
        String response = extracted.getResponse() != null ? extracted.getResponse() : "";
        boolean hasCode = input.contains("```") || response.contains("```")
                || input.contains("kubectl") || input.contains("docker")
                || input.contains("git ") || input.contains("mvn ")
                || input.contains("deploy") || input.contains("config");
        if (hasCode) score += 0.2;

        // Factor 5: Error/debug keywords
        boolean hasError = input.contains("error") || input.contains("fail")
                || input.contains("bug") || input.contains("exception")
                || response.contains("error") || response.contains("fail");
        if (hasError) score += 0.15;

        return Math.min(1.0, Math.max(0.0, score));
    }
}
