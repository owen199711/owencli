package com.owencli.contextos.feedback;

import com.owencli.contextos.feedback.MemoryExtractor.ExtractedContent;
import com.owencli.contextos.feedback.ImportanceScorer.ScoredContent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;

/**
 * Conflict Detector — detects conflicts between new memory and existing stored memories.
 * Prevents contradictory information from being stored without resolution.
 */
public class ConflictDetector {

    private static final Logger log = LoggerFactory.getLogger(ConflictDetector.class);

    public ResolvedContent resolve(ScoredContent scored, List<String> existingMemories) {
        var conflicts = new ArrayList<String>();

        if (existingMemories == null || existingMemories.isEmpty()) {
            log.debug("ConflictDetector: no existing memories to check");
            return new ResolvedContent(scored, conflicts, false);
        }

        String input = scored.getExtracted().getInput() != null ? scored.getExtracted().getInput().toLowerCase() : "";

        for (String existing : existingMemories) {
            if (existing == null) continue;
            String existingLower = existing.toLowerCase();

            // Check for direct contradictions
            if (containsContradiction(input, existingLower)) {
                conflicts.add(existing);
            }
        }

        boolean hasConflict = !conflicts.isEmpty();
        if (hasConflict) {
            log.info("ConflictDetector: detected {} conflict(s) for input: {}",
                    conflicts.size(), truncate(input, 50));
        }

        return new ResolvedContent(scored, conflicts, hasConflict);
    }

    private boolean containsContradiction(String newContent, String existingContent) {
        // Simple heuristic: if same topic but opposite outcomes
        if (!sharesTopic(newContent, existingContent)) return false;

        // Check for negation patterns
        boolean newPositive = !containsNegation(newContent);
        boolean existingPositive = !containsNegation(existingContent);

        return newPositive != existingPositive;
    }

    private boolean sharesTopic(String a, String b) {
        if (a == null || b == null) return false;
        // Extract key nouns/topics (words with 3+ chars)
        var aWords = a.toLowerCase().split("[^a-zA-Z0-9\\u4e00-\\u9fff]+");
        var bWords = b.toLowerCase().split("[^a-zA-Z0-9\\u4e00-\\u9fff]+");
        for (var w : aWords) {
            if (w.length() < 3) continue;
            for (var w2 : bWords) {
                if (w2.length() < 3) continue;
                if (w.equals(w2) || w.contains(w2) || w2.contains(w)) return true;
            }
        }
        return false;
    }

    private boolean containsNegation(String text) {
        if (text == null) return false;
        String lower = text.toLowerCase();
        return lower.contains("not ") || lower.contains("cannot") || lower.contains("can't")
                || lower.contains("don't") || lower.contains("doesn't") || lower.contains("failed")
                || lower.contains("error") || lower.contains("wrong");
    }

    public static class ResolvedContent {
        private final ScoredContent scored;
        private final List<String> conflicts;
        private final boolean hasConflict;

        public ResolvedContent(ScoredContent scored, List<String> conflicts, boolean hasConflict) {
            this.scored = scored;
            this.conflicts = conflicts;
            this.hasConflict = hasConflict;
        }

        public ScoredContent getScored() { return scored; }
        public List<String> getConflicts() { return conflicts; }
        public boolean hasConflict() { return hasConflict; }
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }
}
