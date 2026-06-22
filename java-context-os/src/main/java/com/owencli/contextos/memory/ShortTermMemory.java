package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

public class ShortTermMemory {
    private static final Logger log = LoggerFactory.getLogger(ShortTermMemory.class);

    private final String sessionId;
    private final SQLiteStore store;
    private final int ttlHours;

    public ShortTermMemory(String sessionId, SQLiteStore store) { this(sessionId, store, 24); }
    public ShortTermMemory(String sessionId, SQLiteStore store, int ttlHours) {
        this.sessionId = sessionId; this.store = store; this.ttlHours = ttlHours;
    }

    public CompletableFuture<String> add(String content) { return add(content, null, "anonymous"); }
    public CompletableFuture<String> add(String content, Map<String, Object> metadata, String userId) {
        String memId = UUID.randomUUID().toString().replace("-", "");
        return store.saveMemory(memId, "short_term", content, sessionId, userId, null, metadata, ttlHours * 3600);
    }

    /**
     * Retrieve STM entries matching the given query (keyword OR LIKE).
     * Unlike getAll(), this filters content to avoid returning everything.
     */
    public CompletableFuture<List<MemoryItem>> retrieve(String query, int topK) {
        // Extract keywords from query
        var keywords = extractKeywords(query);
        return store.queryMemories("short_term", sessionId, null, query, keywords, null, topK, 0)
                .thenApply(results -> results.stream().map(r -> {
                    var item = new MemoryItem(MemoryType.CONVERSATION, (String) r.getOrDefault("content", ""));
                    item.setId((String) r.get("id"));
                    item.setRelevanceScore(0.5);
                    return item;
                }).collect(Collectors.toList()));
    }

    public CompletableFuture<List<MemoryItem>> getAll() {
        return store.queryMemories("short_term", sessionId, null, null, null, 100, 0)
                .thenApply(results -> results.stream().map(r -> {
                    var item = new MemoryItem(MemoryType.CONVERSATION, (String) r.getOrDefault("content", ""));
                    item.setId((String) r.get("id"));
                    return item;
                }).collect(Collectors.toList()));
    }

    public CompletableFuture<Void> clear() {
        return store.queryMemories("short_term", sessionId, null, null, null, 1000, 0)
                .thenCompose(results -> CompletableFuture.allOf(
                        results.stream().map(r -> store.deleteMemory((String) r.get("id"))).toArray(CompletableFuture[]::new)))
                .thenAccept(v -> log.info("STM cleared: session={}", sessionId));
    }

    private List<String> extractKeywords(String query) {
        if (query == null || query.isBlank()) return List.of();
        var keywords = new LinkedHashSet<String>();
        var chineseMatcher = Pattern.compile("[\\u4e00-\\u9fff]{2,}").matcher(query);
        while (chineseMatcher.find()) keywords.add(chineseMatcher.group());
        for (var w : query.toLowerCase().split("[^a-zA-Z0-9]+")) { if (w.length() >= 3) keywords.add(w); }
        var result = new ArrayList<>(keywords);
        log.debug("STM keywords: {}", result);
        return result;
    }
}
