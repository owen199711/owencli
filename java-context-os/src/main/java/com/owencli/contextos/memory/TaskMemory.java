package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Task Memory — stores current and historical task execution records.
 * Tracks task status, results, and execution patterns per session.
 */
public class TaskMemory {

    private static final Logger log = LoggerFactory.getLogger(TaskMemory.class);

    private final SQLiteStore store;
    private final String userId;

    public TaskMemory(SQLiteStore store, String userId) {
        this.store = store;
        this.userId = userId;
        log.info("TaskMemory initialized");
    }

    public CompletableFuture<String> recordTask(String taskId, String description, String intent,
                                                  String status, Map<String, Object> result) {
        String memId = UUID.randomUUID().toString().replace("-", "");
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("task_id", taskId);
        metadata.put("intent", intent);
        metadata.put("status", status);
        metadata.put("result", result);
        metadata.put("userId", userId);
        String content = String.format("[Task] %s | intent=%s | status=%s | desc=%s",
                taskId, intent, status, truncate(description, 100));
        return store.saveMemory(memId, "task", content, null, userId, null, metadata, null);
    }

    public CompletableFuture<Void> updateTaskStatus(String taskId, String status) {
        return store.queryMemories("task", null, userId, null, null, 100, 0)
                .thenCompose(results -> {
                    for (var r : results) {
                        if (taskId.equals(r.get("id"))) {
                            String id = (String) r.get("id");
                            Map<String, Object> meta = new LinkedHashMap<>();
                            meta.put("status", status);
                            return store.saveMemory(id, "task", (String) r.get("content"),
                                    null, userId, null, meta, null).thenAccept(v -> {});
                        }
                    }
                    return CompletableFuture.completedFuture(null);
                });
    }

    public CompletableFuture<List<MemoryItem>> getRecentTasks(int limit) {
        return store.queryMemories("task", null, userId, null, null, limit, 0)
                .thenApply(results -> results.stream().map(r -> {
                    var item = new MemoryItem(MemoryType.TASK, (String) r.getOrDefault("content", ""));
                    item.setId((String) r.get("id"));
                    item.setRelevanceScore(0.6);
                    return item;
                }).collect(Collectors.toList()));
    }

    public CompletableFuture<List<MemoryItem>> retrieve(String query, int topK) {
        return store.queryMemories("task", null, userId, query, null, null, topK, 0)
                .thenApply(results -> results.stream().map(r -> {
                    var item = new MemoryItem(MemoryType.TASK, (String) r.getOrDefault("content", ""));
                    item.setId((String) r.get("id"));
                    item.setRelevanceScore(0.6);
                    return item;
                }).collect(Collectors.toList()));
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }
}
