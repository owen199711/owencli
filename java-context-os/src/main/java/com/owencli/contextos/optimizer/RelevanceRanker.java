package com.owencli.contextos.optimizer;

import com.owencli.contextos.core.model.KnowledgeChunk;
import com.owencli.contextos.core.model.MemoryItem;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Comparator;
import java.util.List;
import java.util.stream.Collectors;

/**
 * Relevance ranker — sorts memories and knowledge by relevance.
 */
public class RelevanceRanker {

    private static final Logger log = LoggerFactory.getLogger(RelevanceRanker.class);

    public List<MemoryItem> rankMemories(List<MemoryItem> memories, int topK) {
        var ranked = memories.stream()
                .sorted(Comparator.comparingDouble(MemoryItem::getRelevanceScore).reversed())
                .limit(topK)
                .collect(Collectors.toList());
        log.debug("Ranked memories: {} -> {}", memories.size(), ranked.size());
        return ranked;
    }

    public List<KnowledgeChunk> rankKnowledge(List<KnowledgeChunk> knowledge, int topK) {
        var ranked = knowledge.stream()
                .sorted(Comparator.comparingDouble(KnowledgeChunk::getScore).reversed())
                .limit(topK)
                .collect(Collectors.toList());
        log.debug("Ranked knowledge: {} -> {}", knowledge.size(), ranked.size());
        return ranked;
    }
}
