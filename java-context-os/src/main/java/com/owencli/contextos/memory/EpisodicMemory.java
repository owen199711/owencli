package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

public class EpisodicMemory {
    private static final Logger log = LoggerFactory.getLogger(EpisodicMemory.class);

    private final SQLiteStore store;
    private final String userId;

    public EpisodicMemory(SQLiteStore store, String userId) { this.store = store; this.userId = userId; }

    public CompletableFuture<String> record(String scene, String action, String result, String feedback,
                                            List<String> relatedFiles, List<String> tags, String userId) {
        return store.saveEpisode(scene, action, result, feedback != null ? feedback : "",
                relatedFiles, tags, userId != null ? userId : this.userId);
    }

    public CompletableFuture<String> recordSuccess(String scene, String action, String result,
                                                    List<String> tags, List<String> relatedFiles) {
        List<String> allTags = new ArrayList<>(); if (tags != null) allTags.addAll(tags);
        allTags.add("success");
        return record(scene, action, result, "positive", relatedFiles, allTags, null);
    }

    public CompletableFuture<List<MemoryItem>> recallSimilar(String query, int topK) {
        return store.queryEpisodes(query, null, userId, topK)
                .thenApply(results -> results.stream().map(r -> {
                    String scene = (String) r.getOrDefault("scene", "");
                    String action = (String) r.getOrDefault("action", "");
                    String result = (String) r.getOrDefault("result", "");
                    String feedback = (String) r.getOrDefault("feedback", "");
                    String content = String.format("[Episode] scene=%s | action=%s | result=%s | feedback=%s",
                            truncate(scene, 100), truncate(action, 100), truncate(result, 100), feedback);
                    var item = new MemoryItem(MemoryType.EPISODIC, content);
                    item.setRelevanceScore(0.6);
                    return item;
                }).collect(Collectors.toList()));
    }

    private static String truncate(String s, int max) { return s != null && s.length() > max ? s.substring(0, max) : (s != null ? s : ""); }
}
