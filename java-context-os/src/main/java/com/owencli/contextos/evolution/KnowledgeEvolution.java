package com.owencli.contextos.evolution;

import com.owencli.contextos.memory.SemanticMemory;
import com.owencli.contextos.memory.SQLiteStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Knowledge Evolution — automatically evolves semantic knowledge over time.
 * Clusters related concepts, merges duplicates, summarizes patterns, and updates the graph.
 * <p>
 * Pipeline: Cluster → Merge → Summarize → Concept → Graph Update
 */
public class KnowledgeEvolution {

    private static final Logger log = LoggerFactory.getLogger(KnowledgeEvolution.class);

    private final SemanticMemory semanticMemory;
    private final SQLiteStore store;

    public KnowledgeEvolution(SemanticMemory semanticMemory, SQLiteStore store) {
        this.semanticMemory = semanticMemory;
        this.store = store;
        log.info("KnowledgeEvolution initialized");
    }

    /**
     * Run the full evolution cycle.
     */
    public CompletableFuture<Void> evolve() {
        return extractConcepts()
                .thenCompose(this::clusterConcepts)
                .thenCompose(clusters -> mergeClusters(clusters).thenApply(v -> clusters))
                .thenCompose(this::summarizeClusters)
                .thenCompose(this::updateGraph);
    }

    private CompletableFuture<List<ConceptEntry>> extractConcepts() {
        return store.queryMemories("semantic", null, null, null, null, 1000, 0)
                .thenApply(results -> results.stream()
                        .map(r -> new ConceptEntry(
                                (String) r.get("id"),
                                (String) r.getOrDefault("content", ""),
                                parseMetadata(r.get("metadata")),
                                (double) r.getOrDefault("relevance_score", 0.0)
                        ))
                        .filter(c -> c.name() != null && !c.name().isBlank())
                        .collect(Collectors.toList()));
    }

    private CompletableFuture<List<ConceptCluster>> clusterConcepts(List<ConceptEntry> concepts) {
        if (concepts.size() < 3) {
            return CompletableFuture.completedFuture(
                    concepts.stream().map(c -> new ConceptCluster(c.name(), List.of(c))).collect(Collectors.toList())
            );
        }

        var clusters = new ArrayList<ConceptCluster>();
        var processed = new boolean[concepts.size()];

        for (int i = 0; i < concepts.size(); i++) {
            if (processed[i]) continue;
            var cluster = new ArrayList<ConceptEntry>();
            cluster.add(concepts.get(i));
            processed[i] = true;

            for (int j = i + 1; j < concepts.size(); j++) {
                if (processed[j]) continue;
                double similarity = computeSimilarity(concepts.get(i).name(), concepts.get(j).name());
                if (similarity >= 0.6) {
                    cluster.add(concepts.get(j));
                    processed[j] = true;
                }
            }

            String clusterName = cluster.stream()
                    .map(ConceptEntry::name)
                    .max(Comparator.comparingInt(String::length))
                    .orElse(concepts.get(i).name());
            clusters.add(new ConceptCluster(clusterName, cluster));
        }

        log.info("KnowledgeEvolution: clustered {} concepts into {} groups", concepts.size(), clusters.size());
        return CompletableFuture.completedFuture(clusters);
    }

    private CompletableFuture<Void> mergeClusters(List<ConceptCluster> clusters) {
        var futures = clusters.stream()
                .filter(c -> c.entries().size() > 1)
                .map(cluster -> {
                    // Merge: keep the most comprehensive concept, create relations
                    var main = cluster.entries().get(0);
                    var rest = cluster.entries().subList(1, cluster.entries().size());

                    return CompletableFuture.allOf(
                            rest.stream().map(other ->
                                    semanticMemory.addRelation(main.name(), other.name(), "related_to", 0.8)
                            ).toArray(CompletableFuture[]::new)
                    );
                })
                .toArray(CompletableFuture[]::new);

        return CompletableFuture.allOf(futures);
    }

    private CompletableFuture<Map<String, String>> summarizeClusters(List<ConceptCluster> clusters) {
        var summaries = new LinkedHashMap<String, String>();
        for (var cluster : clusters) {
            String summary = cluster.entries().stream()
                    .map(ConceptEntry::name)
                    .distinct()
                    .collect(Collectors.joining(", "));
            summaries.put(cluster.name(), summary);
        }
        return CompletableFuture.completedFuture(summaries);
    }

    private CompletableFuture<Void> updateGraph(Map<String, String> summaries) {
        return CompletableFuture.allOf(
                summaries.entrySet().stream().map(entry ->
                        semanticMemory.addConcept(
                                "cluster:" + entry.getKey(),
                                Map.of("description", "Auto-clustered concepts: " + entry.getValue(),
                                        "source", "KnowledgeEvolution"),
                                null, 0.7
                        )
                ).toArray(CompletableFuture[]::new)
        ).thenAccept(v -> log.info("KnowledgeEvolution: graph updated with {} cluster summaries", summaries.size()));
    }

    private double computeSimilarity(String a, String b) {
        if (a == null || b == null) return 0.0;
        String lowerA = a.toLowerCase();
        String lowerB = b.toLowerCase();
        if (lowerA.equals(lowerB)) return 1.0;
        if (lowerA.contains(lowerB) || lowerB.contains(lowerA)) return 0.8;
        // Word overlap
        var aWords = new HashSet<>(List.of(lowerA.split("[^a-z0-9]+")));
        var bWords = new HashSet<>(List.of(lowerB.split("[^a-z0-9]+")));
        aWords.removeIf(w -> w.length() < 2);
        bWords.removeIf(w -> w.length() < 2);
        if (aWords.isEmpty() || bWords.isEmpty()) return 0.0;
        var intersection = new HashSet<>(aWords);
        intersection.retainAll(bWords);
        var union = new HashSet<>(aWords);
        union.addAll(bWords);
        return (double) intersection.size() / union.size();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseMetadata(Object metadata) {
        if (metadata instanceof Map m) return (Map<String, Object>) m;
        return Map.of();
    }

    private record ConceptEntry(String id, String name, Map<String, Object> metadata, double score) {}
    private record ConceptCluster(String name, List<ConceptEntry> entries) {}
}
