package com.owencli.contextos.optimizer;

import com.owencli.contextos.core.model.MemoryItem;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Chunk Merger — merges similar memory chunks to reduce redundancy.
 * 20 memory items often contain 18 duplicates. Merge them instead of sending all.
 */
public class ChunkMerger {

    private static final Logger log = LoggerFactory.getLogger(ChunkMerger.class);
    private static final double SIMILARITY_THRESHOLD = 0.75;

    public List<MemoryItem> merge(List<MemoryItem> items) {
        if (items == null || items.size() <= 1) return items;

        int before = items.size();
        var merged = new ArrayList<MemoryItem>();
        var processed = new boolean[items.size()];

        for (int i = 0; i < items.size(); i++) {
            if (processed[i]) continue;
            var base = items.get(i);
            var similarItems = new ArrayList<MemoryItem>();
            similarItems.add(base);

            for (int j = i + 1; j < items.size(); j++) {
                if (processed[j]) continue;
                if (computeSimilarity(base.getContent(), items.get(j).getContent()) >= SIMILARITY_THRESHOLD) {
                    similarItems.add(items.get(j));
                    processed[j] = true;
                }
            }

            if (similarItems.size() > 1) {
                // Merge: keep the longest content with the highest relevance score
                var mergedItem = similarItems.stream()
                        .max(Comparator.comparingInt(m -> m.getContent().length()))
                        .orElse(base);
                mergedItem.setRelevanceScore(
                        similarItems.stream().mapToDouble(MemoryItem::getRelevanceScore).max().orElse(0));
                merged.add(mergedItem);
                log.trace("Merged {} similar items into one", similarItems.size());
            } else {
                merged.add(base);
            }
        }

        int after = merged.size();
        if (after < before) {
            log.info("ChunkMerger: merged {} items into {} (saved {})", before, after, before - after);
        }
        return merged;
    }

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
}
