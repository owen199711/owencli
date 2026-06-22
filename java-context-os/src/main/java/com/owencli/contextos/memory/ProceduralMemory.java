package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Procedural Memory — stores learned procedures, workflows, and step-by-step patterns.
 * Captures "how to do X" knowledge that the agent accumulates over time.
 */
public class ProceduralMemory {

    private static final Logger log = LoggerFactory.getLogger(ProceduralMemory.class);

    private final SQLiteStore store;
    private final String userId;

    public ProceduralMemory(SQLiteStore store, String userId) {
        this.store = store;
        this.userId = userId;
        log.info("ProceduralMemory initialized");
    }

    public CompletableFuture<String> recordProcedure(String procedureName, String steps,
                                                       String domain, double successRate,
                                                       Map<String, Object> metadata) {
        String memId = UUID.randomUUID().toString().replace("-", "");
        Map<String, Object> enrichedMeta = metadata != null ? new LinkedHashMap<>(metadata) : new LinkedHashMap<>();
        enrichedMeta.put("procedure_name", procedureName);
        enrichedMeta.put("domain", domain);
        enrichedMeta.put("success_rate", successRate);
        enrichedMeta.put("userId", userId);

        String content = String.format("[Procedure] %s | domain=%s | success_rate=%.2f\nSteps:\n%s",
                procedureName, domain, successRate, steps);
        return store.saveMemory(memId, "procedural", content, null, userId, null, enrichedMeta, null);
    }

    public CompletableFuture<List<MemoryItem>> retrieve(String query, String domain, int topK) {
        return store.queryMemories("procedural", null, userId, query, null, null, topK, 0)
                .thenApply(results -> results.stream()
                        .filter(r -> domain == null || domain.equals(
                                ((Map<String, Object>) r.getOrDefault("metadata", Map.of())).get("domain")))
                        .map(r -> {
                            var item = new MemoryItem(MemoryType.PROCEDURAL, (String) r.getOrDefault("content", ""));
                            item.setId((String) r.get("id"));
                            item.setRelevanceScore(0.7);
                            return item;
                        }).collect(Collectors.toList()));
    }

    public CompletableFuture<Void> updateSuccessRate(String procedureName, boolean success) {
        return store.queryMemories("procedural", null, userId, null, null, 100, 0)
                .thenCompose(results -> {
                    for (var r : results) {
                        String content = (String) r.getOrDefault("content", "");
                        if (content.contains(procedureName)) {
                            String id = (String) r.get("id");
                            double current = (double) r.getOrDefault("relevance_score", 0.0);
                            double updated = success ? Math.min(1.0, current + 0.1) : Math.max(0.0, current - 0.1);
                            Map<String, Object> meta = new LinkedHashMap<>();
                            meta.put("success_rate", updated);
                            return store.saveMemory(id, "procedural", content, null, userId, null, meta, null)
                                    .thenAccept(v -> {});
                        }
                    }
                    return CompletableFuture.completedFuture(null);
                });
    }
}
