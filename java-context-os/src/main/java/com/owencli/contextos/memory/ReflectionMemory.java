package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Reflection Memory — stores agent self-reflections and learned lessons.
 * After task completion, the agent reflects on what went wrong and stores
 * corrective knowledge to prevent repeating mistakes.
 */
public class ReflectionMemory {

    private static final Logger log = LoggerFactory.getLogger(ReflectionMemory.class);

    private final SQLiteStore store;
    private final String userId;

    public ReflectionMemory(SQLiteStore store, String userId) {
        this.store = store;
        this.userId = userId;
        log.info("ReflectionMemory initialized");
    }

    public CompletableFuture<String> addReflection(String taskDescription, String outcome,
                                                     String rootCause, String lesson,
                                                     List<String> preventiveActions,
                                                     Map<String, Object> metadata) {
        String memId = UUID.randomUUID().toString().replace("-", "");

        Map<String, Object> enrichedMeta = metadata != null ? new LinkedHashMap<>(metadata) : new LinkedHashMap<>();
        enrichedMeta.put("task", taskDescription);
        enrichedMeta.put("outcome", outcome);
        enrichedMeta.put("root_cause", rootCause);
        enrichedMeta.put("lesson", lesson);
        enrichedMeta.put("preventive_actions", preventiveActions);
        enrichedMeta.put("userId", userId);

        String content = String.format("[Reflection] task=%s | outcome=%s\nRoot Cause: %s\nLesson: %s\nPrevention: %s",
                truncate(taskDescription, 80), outcome, rootCause, lesson,
                String.join("; ", preventiveActions));

        return store.saveMemory(memId, "reflection", content, null, userId, null, enrichedMeta, null);
    }

    public CompletableFuture<List<MemoryItem>> retrieve(String query, int topK) {
        return store.queryMemories("reflection", null, userId, query, null, null, topK, 0)
                .thenApply(results -> results.stream().map(r -> {
                    var item = new MemoryItem(MemoryType.REFLECTION, (String) r.getOrDefault("content", ""));
                    item.setId((String) r.get("id"));
                    item.setRelevanceScore(0.8);
                    return item;
                }).collect(Collectors.toList()));
    }

    public CompletableFuture<List<MemoryItem>> retrieveByRootCause(String rootCause, int topK) {
        return store.queryMemories("reflection", null, userId, rootCause, null, null, topK, 0)
                .thenApply(results -> results.stream().map(r -> {
                    var item = new MemoryItem(MemoryType.REFLECTION, (String) r.getOrDefault("content", ""));
                    item.setId((String) r.get("id"));
                    item.setRelevanceScore(0.9);
                    return item;
                }).collect(Collectors.toList()));
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }
}
