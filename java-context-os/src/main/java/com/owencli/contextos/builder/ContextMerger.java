package com.owencli.contextos.builder;

import com.owencli.contextos.core.model.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Context merger — merges, normalizes, and deduplicates context sources.
 */
public class ContextMerger {

    private static final Logger log = LoggerFactory.getLogger(ContextMerger.class);

    public UnifiedContext merge(List<UnifiedContext> contexts) {
        if (contexts.isEmpty()) return new UnifiedContext();
        if (contexts.size() == 1) return contexts.get(0);

        var result = new UnifiedContext();

        for (var ctx : contexts) {
            if (ctx.getIdentity() != null && result.getIdentity() == null)
                result.setIdentity(ctx.getIdentity());
            if (ctx.getConversation() != null && result.getConversation() == null)
                result.setConversation(ctx.getConversation());
            if (ctx.getEnvironment() != null && result.getEnvironment() == null)
                result.setEnvironment(ctx.getEnvironment());
        }

        var seenMemoryIds = new HashSet<String>();
        var seenKnowledge = new HashSet<String>();
        var seenToolNames = new HashSet<String>();

        for (var ctx : contexts) {
            for (var m : ctx.getMemory()) {
                if (seenMemoryIds.add(m.getId())) result.getMemory().add(m);
            }
            for (var k : ctx.getKnowledge()) {
                String key = k.getSource() + ":" + truncate(k.getContent(), 50);
                if (seenKnowledge.add(key)) result.getKnowledge().add(k);
            }
            for (var t : ctx.getTools()) {
                if (seenToolNames.add(t.getName())) result.getTools().add(t);
            }
        }

        log.debug("Merged {} contexts: memories={}, knowledge={}, tools={}",
                contexts.size(), result.getMemory().size(), result.getKnowledge().size(), result.getTools().size());
        return result;
    }

    public UnifiedContext normalize(UnifiedContext context) {
        context.getMemory().sort((a, b) -> Double.compare(b.getRelevanceScore(), a.getRelevanceScore()));
        context.getKnowledge().sort((a, b) -> Double.compare(b.getScore(), a.getScore()));
        context.getTools().sort(Comparator.comparing(ToolContext::getName));
        return context;
    }

    public UnifiedContext deduplicate(UnifiedContext context) {
        // Memory dedup
        var seenMemory = new LinkedHashMap<String, MemoryItem>();
        for (var item : context.getMemory()) {
            String key = item.getContent().strip();
            var existing = seenMemory.get(key);
            if (existing == null || item.getRelevanceScore() > existing.getRelevanceScore()) {
                seenMemory.put(key, item);
            }
        }
        context.setMemory(new ArrayList<>(seenMemory.values()));

        // Knowledge dedup
        var seenKnowledge = new LinkedHashMap<String, KnowledgeChunk>();
        for (var k : context.getKnowledge()) {
            String key = k.getContent().strip();
            var existing = seenKnowledge.get(key);
            if (existing == null || k.getScore() > existing.getScore()) {
                seenKnowledge.put(key, k);
            }
        }
        context.setKnowledge(new ArrayList<>(seenKnowledge.values()));

        return context;
    }

    private static String truncate(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max);
    }
}
