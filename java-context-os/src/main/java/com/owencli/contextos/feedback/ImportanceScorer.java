package com.owencli.contextos.feedback;

import com.owencli.contextos.feedback.MemoryExtractor.ExtractedContent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Importance Scorer — computes the importance score of extracted memory content.
 * Not all information is worth persisting. Score threshold: 0.0 - 1.0.
 * Only items with score > 0.75 are saved to long-term memory.
 */
public class ImportanceScorer {

    private static final Logger log = LoggerFactory.getLogger(ImportanceScorer.class);

    private static final double SAVE_THRESHOLD = 0.75;

    public ScoredContent score(ExtractedContent extracted) {
        double score = 0.0;

        // Factor 1: Success (successful outcomes are more valuable)
        if (extracted.isSuccess()) score += 0.2;

        // Factor 2: Input length and complexity (longer inputs are more substantive)
        int inputLen = extracted.getInput() != null ? extracted.getInput().length() : 0;
        if (inputLen > 100) score += 0.25;
        else if (inputLen > 50) score += 0.15;
        else if (inputLen > 20) score += 0.05;

        // Factor 3: Has key concepts/entities
        int conceptCount = extracted.getKeyConcepts() != null ? extracted.getKeyConcepts().size() : 0;
        if (conceptCount >= 3) score += 0.3;
        else if (conceptCount >= 1) score += 0.15;

        // Factor 4: Technical/coding content
        String input = extracted.getInput() != null ? extracted.getInput() : "";
        String response = extracted.getResponse() != null ? extracted.getResponse() : "";
        boolean hasCode = input.contains("```") || response.contains("```")
                || input.contains("kubectl") || input.contains("docker")
                || input.contains("git ") || input.contains("mvn ")
                || input.contains("deploy") || input.contains("config");
        if (hasCode) score += 0.2;

        // Factor 5: Error/debug content (valuable for learning)
        boolean hasError = input.contains("error") || input.contains("fail")
                || input.contains("bug") || input.contains("exception")
                || response.contains("error") || response.contains("fail");
        if (hasError) score += 0.15;

        // Clamp to [0, 1]
        score = Math.min(1.0, Math.max(0.0, score));

        boolean shouldSave = score >= SAVE_THRESHOLD;
        log.debug("ImportanceScorer: score={}, shouldSave={}, input_len={}, concepts={}",
                String.format("%.2f", score), shouldSave, inputLen, conceptCount);

        return new ScoredContent(extracted, score, shouldSave);
    }

    public static class ScoredContent {
        private final ExtractedContent extracted;
        private final double score;
        private final boolean shouldSave;

        public ScoredContent(ExtractedContent extracted, double score, boolean shouldSave) {
            this.extracted = extracted;
            this.score = score;
            this.shouldSave = shouldSave;
        }

        public ExtractedContent getExtracted() { return extracted; }
        public double getScore() { return score; }
        public boolean isShouldSave() { return shouldSave; }
    }
}
