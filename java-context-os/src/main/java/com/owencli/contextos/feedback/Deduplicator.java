package com.owencli.contextos.feedback;

import com.owencli.contextos.feedback.ConflictDetector.ResolvedContent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;

/**
 * Deduplicator — removes duplicate or near-duplicate content before writing to memory.
 * Uses content similarity heuristics to identify and merge duplicates.
 */
public class Deduplicator {

    private static final Logger log = LoggerFactory.getLogger(Deduplicator.class);

    private static final double SIMILARITY_THRESHOLD = 0.85;

    public DeduplicationResult deduplicate(ResolvedContent resolved, List<String> existingContents) {
        var newEntry = resolved.getScored().getExtracted().getTaskEntry();
        if (newEntry == null || newEntry.isEmpty()) {
            return new DeduplicationResult(resolved, false, existingContents);
        }

        var merged = new ArrayList<>(existingContents);
        var duplicates = new ArrayList<String>();
        boolean isDuplicate = false;

        for (String existing : existingContents) {
            if (existing == null) continue;
            double similarity = computeSimilarity(newEntry, existing);
            if (similarity >= SIMILARITY_THRESHOLD) {
                duplicates.add(existing);
                isDuplicate = true;
            }
        }

        // If duplicate found, keep the more complete version
        if (isDuplicate) {
            // Remove all duplicates, keep the longer/newer version
            merged.removeAll(duplicates);
            merged.add(newEntry);
            merged = new ArrayList<>(new LinkedHashSet<>(merged)); // preserve order and deduplicate
            log.info("Deduplicator: merged {} duplicate(s) into one entry", duplicates.size());
        } else {
            merged.add(newEntry);
        }

        return new DeduplicationResult(resolved, isDuplicate, merged);
    }

    /**
     * Compute Jaccard-like similarity between two strings based on word overlap.
     */
    private double computeSimilarity(String a, String b) {
        if (a == null || b == null) return 0.0;
        if (a.equals(b)) return 1.0;

        var aWords = new LinkedHashSet<>(List.of(a.toLowerCase().split("[^a-zA-Z0-9\\u4e00-\\u9fff]+")));
        var bWords = new LinkedHashSet<>(List.of(b.toLowerCase().split("[^a-zA-Z0-9\\u4e00-\\u9fff]+")));

        aWords.removeIf(w -> w.length() < 2);
        bWords.removeIf(w -> w.length() < 2);

        if (aWords.isEmpty() && bWords.isEmpty()) return 0.0;

        var intersection = new LinkedHashSet<>(aWords);
        intersection.retainAll(bWords);

        var union = new LinkedHashSet<>(aWords);
        union.addAll(bWords);

        return (double) intersection.size() / union.size();
    }

    public static class DeduplicationResult {
        private final ResolvedContent resolved;
        private final boolean wasDuplicate;
        private final List<String> mergedContents;

        public DeduplicationResult(ResolvedContent resolved, boolean wasDuplicate, List<String> mergedContents) {
            this.resolved = resolved;
            this.wasDuplicate = wasDuplicate;
            this.mergedContents = mergedContents;
        }

        public ResolvedContent getResolved() { return resolved; }
        public boolean isWasDuplicate() { return wasDuplicate; }
        public List<String> getMergedContents() { return mergedContents; }
    }
}
