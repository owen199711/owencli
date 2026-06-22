package com.owencli.contextos.memory;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;

/**
 * Semantic Memory — knowledge graph of concepts and relations.
 */
public class SemanticMemory {

    private static final Logger log = LoggerFactory.getLogger(SemanticMemory.class);

    private final SQLiteStore store;
    private final String userId;

    public SemanticMemory(SQLiteStore store, String userId) {
        this.store = store;
        this.userId = userId;
        log.info("SemanticMemory initialized");
    }

    public CompletableFuture<String> addConcept(String name, Map<String, Object> attributes,
                                                List<Double> embedding, double confidence) {
        return store.saveConcept(name, attributes, embedding, confidence, userId)
                .thenApply(cid -> {
                    log.info("Concept added/updated: name='{}', confidence={}", name, confidence);
                    return cid;
                });
    }

    public CompletableFuture<String> addRelation(String source, String target,
                                                 String relationType, double weight) {
        return store.saveRelation(source, target, relationType, weight)
                .thenApply(rid -> {
                    log.info("Relation saved: {} --[{}]--> {}", source, relationType, target);
                    return rid;
                });
    }

    public CompletableFuture<Map<String, Object>> queryGraph(String conceptName, int depth) {
        return store.queryGraph(conceptName, depth)
                .thenApply(result -> {
                    log.debug("Graph query '{}' depth={}: {} nodes, {} edges",
                            conceptName, depth,
                            ((List<?>) result.getOrDefault("nodes", List.of())).size(),
                            ((List<?>) result.getOrDefault("edges", List.of())).size());
                    return result;
                });
    }
}
