package com.owencli.contextos.lifecycle;

import com.owencli.contextos.memory.SQLiteStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Memory Lifecycle — manages the full lifecycle of memory items.
 * <p>
 * Pipeline: Write → Consolidate → Summarize → Archive → Forget
 * <p>
 * Prevents unbounded growth of the SQLite store by archiving and forgetting
 * old, low-importance memories.
 */
public class MemoryLifecycle {

    private static final Logger log = LoggerFactory.getLogger(MemoryLifecycle.class);

    private final SQLiteStore store;
    private final int archiveAfterDays;
    private final int forgetAfterDays;

    public MemoryLifecycle(SQLiteStore store) {
        this(store, 30, 90);
    }

    public MemoryLifecycle(SQLiteStore store, int archiveAfterDays, int forgetAfterDays) {
        this.store = store;
        this.archiveAfterDays = archiveAfterDays;
        this.forgetAfterDays = forgetAfterDays;
        log.info("MemoryLifecycle: archive={}d, forget={}d", archiveAfterDays, forgetAfterDays);
    }

    /**
     * Run the full lifecycle maintenance cycle.
     */
    public CompletableFuture<Void> runMaintenance() {
        return consolidate()
                .thenCompose(v -> archive())
                .thenCompose(v -> forget())
                .thenRun(() -> log.info("MemoryLifecycle maintenance complete"));
    }

    /**
     * Consolidate: merge similar redundant memories.
     */
    public CompletableFuture<Integer> consolidate() {
        return store.queryMemories("long_term", null, null, null, null, null, 1000, 0)
                .thenApply(results -> {
                    var seen = new java.util.HashSet<String>();
                    var toDelete = new ArrayList<String>();
                    for (var r : results) {
                        String content = ((String) r.getOrDefault("content", "")).trim().toLowerCase();
                        if (seen.contains(content)) {
                            toDelete.add((String) r.get("id"));
                        } else {
                            seen.add(content);
                        }
                    }
                    return toDelete;
                })
                .thenCompose(toDelete -> {
                    if (toDelete.isEmpty()) return CompletableFuture.completedFuture(0);
                    return CompletableFuture.allOf(
                            toDelete.stream().map(store::deleteMemory).toArray(CompletableFuture[]::new)
                    ).thenApply(v -> toDelete.size());
                })
                .thenApply(count -> {
                    if (count > 0) log.info("Consolidate: removed {} duplicate memories", count);
                    return count;
                });
    }

    /**
     * Archive: mark old memories as archived (only keep a summary).
     */
    public CompletableFuture<Integer> archive() {
        var cutoff = Instant.now().minus(Duration.ofDays(archiveAfterDays));
        return store.queryMemories("long_term", null, null, null, null, null, 1000, 0)
                .thenApply(results -> {
                    var toArchive = new ArrayList<Map<String, Object>>();
                    for (var r : results) {
                        String ts = (String) r.getOrDefault("timestamp", "");
                        if (!ts.isBlank()) {
                            try {
                                var timestamp = Instant.parse(ts.replace(" ", "T") + "Z");
                                if (timestamp.isBefore(cutoff)) {
                                    toArchive.add(r);
                                }
                            } catch (Exception ignored) {}
                        }
                    }
                    return toArchive;
                })
                .thenCompose(toArchive -> {
                    if (toArchive.isEmpty()) return CompletableFuture.completedFuture(0);
                    var futures = toArchive.stream().map(r -> {
                        String id = (String) r.get("id");
                        String content = (String) r.getOrDefault("content", "");
                        // Replace with a concise summary
                        String summary = content.length() > 60
                                ? "[Archived] " + content.substring(0, 60) + "..."
                                : "[Archived] " + content;
                        Map<String, Object> meta = Map.of("archived", true, "original_id", id);
                        return store.saveMemory(id, "archived", summary, null, null, null, meta, null);
                    }).toArray(CompletableFuture[]::new);
                    return CompletableFuture.allOf(futures).thenApply(v -> toArchive.size());
                })
                .thenApply(count -> {
                    if (count > 0) log.info("Archive: archived {} old memories", count);
                    return count;
                });
    }

    /**
     * Forget: permanently delete very old or unimportant memories.
     */
    public CompletableFuture<Integer> forget() {
        var cutoff = Instant.now().minus(Duration.ofDays(forgetAfterDays));
        return store.queryMemories("long_term", null, null, null, null, null, 1000, 0)
                .thenApply(results -> {
                    var toForget = new ArrayList<String>();
                    for (var r : results) {
                        String ts = (String) r.getOrDefault("timestamp", "");
                        if (!ts.isBlank()) {
                            try {
                                var timestamp = Instant.parse(ts.replace(" ", "T") + "Z");
                                if (timestamp.isBefore(cutoff)) {
                                    toForget.add((String) r.get("id"));
                                }
                            } catch (Exception ignored) {}
                        }
                    }
                    return toForget;
                })
                .thenCompose(toForget -> {
                    if (toForget.isEmpty()) return CompletableFuture.completedFuture(0);
                    return CompletableFuture.allOf(
                            toForget.stream().map(store::deleteMemory).toArray(CompletableFuture[]::new)
                    ).thenApply(v -> toForget.size());
                })
                .thenApply(count -> {
                    if (count > 0) log.info("Forget: permanently deleted {} old memories", count);
                    return count;
                });
    }
}
