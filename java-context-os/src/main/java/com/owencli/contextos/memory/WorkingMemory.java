package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

import static java.util.Collections.unmodifiableList;

/**
 * Working memory — current session active context.
 * Pure in-memory circular buffer. Not persisted.
 */
public class WorkingMemory {

    private static final Logger log = LoggerFactory.getLogger(WorkingMemory.class);

    private final List<MemoryItem> items = new ArrayList<>();
    private final int maxTokens;
    private int currentTokens = 0;

    public WorkingMemory() {
        this(8000);
    }

    public WorkingMemory(int maxTokens) {
        this.maxTokens = maxTokens;
        log.info("WorkingMemory initialized (max_tokens={})", maxTokens);
    }

    public List<MemoryItem> getItems() { return unmodifiableList(new ArrayList<>(items)); }
    public int getItemCount() { return items.size(); }
    public int getTokenUsage() { return currentTokens; }
    public int getMaxTokens() { return maxTokens; }

    public double getTokenUtilization() {
        return maxTokens > 0 ? (double) currentTokens / maxTokens : 0.0;
    }

    public MemoryItem push(String content) {
        return push(content, new HashMap<>());
    }

    public MemoryItem push(String content, Map<String, Object> metadata) {
        var item = new MemoryItem(MemoryType.WORKING, content);
        item.setMetadata(metadata);

        int itemTokens = estimateTokens(content);
        currentTokens += itemTokens;
        items.add(item);
        evictIfNeeded();

        log.debug("Working memory push: tokens={}, total_tokens={}/{}", itemTokens, currentTokens, maxTokens);
        return item;
    }

    public List<MemoryItem> getRecent(int n) {
        int start = Math.max(0, items.size() - n);
        return items.subList(start, items.size());
    }

    public Optional<MemoryItem> pop() {
        if (items.isEmpty()) return Optional.empty();
        var item = items.remove(items.size() - 1);
        currentTokens -= estimateTokens(item.getContent());
        return Optional.of(item);
    }

    public Optional<MemoryItem> peek() {
        return items.isEmpty() ? Optional.empty() : Optional.of(items.get(items.size() - 1));
    }

    public void clear() {
        items.clear();
        currentTokens = 0;
        log.info("Working memory cleared");
    }

    public List<MemoryItem> find(String keyword) {
        String kw = keyword.toLowerCase();
        return items.stream()
                .filter(item -> item.getContent().toLowerCase().contains(kw))
                .collect(Collectors.toList());
    }

    public String getAttentionContext(int maxTokens) {
        var scored = items.stream()
                .map(item -> {
                    int priority = item.getMetadata() != null
                            ? (int) item.getMetadata().getOrDefault("priority", 0)
                            : 0;
                    return new AbstractMap.SimpleEntry<>(priority, item);
                })
                .sorted(Map.Entry.<Integer, MemoryItem>comparingByKey().reversed())
                .collect(Collectors.toList());

        int resultTokens = 0;
        var parts = new ArrayList<String>();
        for (var entry : scored) {
            var item = entry.getValue();
            int tokens = estimateTokens(item.getContent());
            if (resultTokens + tokens > maxTokens) continue;
            resultTokens += tokens;
            parts.add(item.getContent());
        }

        return String.join("\n", parts);
    }

    private void evictIfNeeded() {
        while (currentTokens > maxTokens && !items.isEmpty()) {
            var evicted = items.remove(0);
            int evictedTokens = estimateTokens(evicted.getContent());
            currentTokens -= evictedTokens;
            log.debug("Evicted oldest item: tokens={}, remaining={}/{}", evictedTokens, currentTokens, maxTokens);
        }
    }

    public static int estimateTokens(String text) {
        long chineseChars = text.chars().filter(c -> c >= 0x4e00 && c <= 0x9fff).count();
        long otherChars = text.length() - chineseChars;
        return (int) (chineseChars * 1.5 + otherChars * 0.25) + 1;
    }
}
