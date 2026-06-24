package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Long-term Index — global vector retrieval layer across all memory types.
 * <p>
 * Not a memory store itself. Instead, it queries ALL vectorized memory stores
 * (LTM, Episodic, Semantic) in parallel, fuses results by relevance score,
 * and returns a deduplicated, ranked list.
 * <p>
 * This replaces the old ContextBuilder's inline multi-source retrieval with
 * a centralized, reusable index.
 */
public class LongTermIndex {

    private static final Logger log = LoggerFactory.getLogger(LongTermIndex.class);

    private final LongTermMemory longTerm;
    private final EpisodicMemory episodic;
    private final SemanticMemory semantic;

    public LongTermIndex(LongTermMemory longTerm, EpisodicMemory episodic, SemanticMemory semantic) {
        this.longTerm = longTerm;
        this.episodic = episodic;
        this.semantic = semantic;
        log.info("LongTermIndex initialized");
    }

    /**
     * Query across all indexed memory types.
     *
     * @param query      Search query
     * @param topK       Number of results per source
     * @return Fused, deduplicated, ranked results
     */
    public CompletableFuture<IndexResult> query(String query, int topK) {
        long start = System.currentTimeMillis();

        CompletableFuture<List<MemoryItem>> ltmFuture = longTerm.retrieve(query, topK, null, null);
        CompletableFuture<List<MemoryItem>> epFuture = episodic.recallSimilar(query, topK);
        CompletableFuture<List<KnowledgeChunkResult>> semFuture = querySemantic(query, topK);

        return CompletableFuture.allOf(ltmFuture, epFuture, semFuture)
                .thenApply(v -> {
                    var all = new ArrayList<MemoryItem>();
                    try {
                        var ltmItems = ltmFuture.get();
                        ltmItems.forEach(i -> i.setRelevanceScore(i.getRelevanceScore() * 0.9));
                        all.addAll(ltmItems);
                    } catch (Exception e) { log.warn("LTM query failed", e); }

                    try {
                        var epItems = epFuture.get();
                        epItems.forEach(i -> i.setRelevanceScore(i.getRelevanceScore() * 0.8));
                        all.addAll(epItems);
                    } catch (Exception e) { log.warn("Episodic query failed", e); }

                    try {
                        var semResults = semFuture.get();
                        for (var sr : semResults) {
                            var item = new MemoryItem(MemoryType.SEMANTIC, String.format(
                                    "[Concept] %s | %s", sr.concept, sr.relationSummary));
                            item.setRelevanceScore(0.85 * sr.relevance);
                            all.add(item);
                        }
                    } catch (Exception e) { log.warn("Semantic query failed", e); }

                    // Deduplicate by content hash
                    var seen = new HashSet<String>();
                    var deduped = new ArrayList<MemoryItem>();
                    for (var item : all) {
                        String key = item.getContent().hashCode() + ":" + item.getType().name();
                        if (seen.add(key)) deduped.add(item);
                    }

                    // Sort by relevance
                    deduped.sort((a, b) -> Double.compare(b.getRelevanceScore(), a.getRelevanceScore()));

                    long elapsed = System.currentTimeMillis() - start;
                    return new IndexResult(deduped, deduped.size(), elapsed);
                });
    }

    private CompletableFuture<List<KnowledgeChunkResult>> querySemantic(String query, int topK) {
        // Extract concepts from query, query graph for each
        var concepts = extractConcepts(query);
        if (concepts.isEmpty()) return CompletableFuture.completedFuture(List.of());

        var futures = concepts.stream()
                .limit(topK)
                .map(c -> semantic.queryGraph(c, 1)
                        .thenApply(graph -> {
                            var nodes = (List<?>) graph.getOrDefault("nodes", List.of());
                            var edges = (List<?>) graph.getOrDefault("edges", List.of());
                            if (nodes.isEmpty() && edges.isEmpty()) return null;
                            String relSummary = edges.stream()
                                    .map(e -> {
                                        if (e instanceof Map<?, ?> m)
                                            return m.get("source") + " --" + m.get("type") + "--> " + m.get("target");
                                        return "";
                                    })
                                    .filter(s -> !s.isEmpty())
                                    .collect(Collectors.joining("; "));
                            return new KnowledgeChunkResult(c, relSummary, edges.size() > 0 ? 0.8 : 0.5);
                        }))
                .toList();

        return CompletableFuture.allOf(futures.toArray(new CompletableFuture<?>[0]))
                .thenApply(v -> futures.stream()
                        .map(f -> {
                            try { return f.join(); } catch (Exception e) { return null; }
                        })
                        .filter(Objects::nonNull)
                        .collect(Collectors.toList()));
    }

    private List<String> extractConcepts(String query) {
        if (query == null || query.isBlank()) return List.of();
        var concepts = new LinkedHashSet<String>();
        var chineseMatcher = java.util.regex.Pattern.compile("[\\u4e00-\\u9fff]{2,}").matcher(query);
        while (chineseMatcher.find()) concepts.add(chineseMatcher.group());
        for (var w : query.toLowerCase().split("[^a-zA-Z0-9]+")) {
            if (w.length() >= 3) concepts.add(w);
        }
        return new ArrayList<>(concepts);
    }

    public record IndexResult(List<MemoryItem> items, int totalSources, long elapsedMs) {}
    private record KnowledgeChunkResult(String concept, String relationSummary, double relevance) {}
}
