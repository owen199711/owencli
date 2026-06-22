package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Conversation Memory — stores session-level conversation history.
 * Replaces the original ShortTermMemory with session-scoped dialogue tracking.
 */
public class ConversationMemory {

    private static final Logger log = LoggerFactory.getLogger(ConversationMemory.class);

    private final String sessionId;
    private final SQLiteStore store;
    private final int ttlHours;

    public ConversationMemory(String sessionId, SQLiteStore store) {
        this(sessionId, store, 24);
    }

    public ConversationMemory(String sessionId, SQLiteStore store, int ttlHours) {
        this.sessionId = sessionId;
        this.store = store;
        this.ttlHours = ttlHours;
    }

    public CompletableFuture<String> addTurn(String role, String content) {
        return addTurn(role, content, null);
    }

    public CompletableFuture<String> addTurn(String role, String content, Map<String, Object> metadata) {
        String memId = UUID.randomUUID().toString().replace("-", "");
        Map<String, Object> enrichedMeta = metadata != null ? new LinkedHashMap<>(metadata) : new LinkedHashMap<>();
        enrichedMeta.put("role", role);
        enrichedMeta.put("session_id", sessionId);
        return store.saveMemory(memId, "conversation", role + ": " + content, sessionId, null,
                null, enrichedMeta, ttlHours * 3600);
    }

    public CompletableFuture<List<MemoryItem>> retrieve(String query, int topK) {
        var keywords = extractKeywords(query);
        return store.queryMemories("conversation", sessionId, null, query, keywords, null, topK, 0)
                .thenApply(results -> results.stream().map(r -> {
                    var item = new MemoryItem(MemoryType.CONVERSATION, (String) r.getOrDefault("content", ""));
                    item.setId((String) r.get("id"));
                    item.setRelevanceScore(0.5);
                    return item;
                }).collect(Collectors.toList()));
    }

    public CompletableFuture<List<MemoryItem>> getRecent(int limit) {
        return store.queryMemories("conversation", sessionId, null, null, null, limit, 0)
                .thenApply(results -> results.stream().map(r -> {
                    var item = new MemoryItem(MemoryType.CONVERSATION, (String) r.getOrDefault("content", ""));
                    item.setId((String) r.get("id"));
                    return item;
                }).collect(Collectors.toList()));
    }

    public CompletableFuture<Void> clear() {
        return store.queryMemories("conversation", sessionId, null, null, null, 1000, 0)
                .thenCompose(results -> CompletableFuture.allOf(
                        results.stream().map(r -> store.deleteMemory((String) r.get("id")))
                                .toArray(CompletableFuture[]::new)))
                .thenAccept(v -> log.info("Conversation memory cleared: session={}", sessionId));
    }

    private List<String> extractKeywords(String query) {
        if (query == null || query.isBlank()) return List.of();
        var keywords = new LinkedHashSet<String>();
        var chineseMatcher = Pattern.compile("[\\u4e00-\\u9fff]{2,}").matcher(query);
        while (chineseMatcher.find()) keywords.add(chineseMatcher.group());
        for (var w : query.toLowerCase().split("[^a-zA-Z0-9]+")) {
            if (w.length() >= 3) keywords.add(w);
        }
        return new ArrayList<>(keywords);
    }
}
