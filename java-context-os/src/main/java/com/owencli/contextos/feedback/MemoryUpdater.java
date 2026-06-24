package com.owencli.contextos.feedback;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.model.EvalMetrics;
import com.owencli.contextos.core.model.TaskSpec;
import com.owencli.contextos.feedback.extraction.MemoryExtractionEngine;
import com.owencli.contextos.importances.MemoryImportanceEngine;
import com.owencli.contextos.importances.StorageTier;
import com.owencli.contextos.memory.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;

public class MemoryUpdater {

    private static final Logger log = LoggerFactory.getLogger(MemoryUpdater.class);

    private final MemoryExtractionEngine extractionEngine;
    private final MemoryImportanceEngine importanceEngine;
    private final ConflictDetector conflictDetector;
    private final Deduplicator deduplicator;
    private final MemoryWriter writer;

    public MemoryUpdater(WorkingMemory working, ConversationMemory conversation,
                         LearnedBehaviorMemory learnedBehavior,
                         LongTermMemory longTerm, EpisodicMemory episodic,
                         SemanticMemory semantic,
                         BaseLLMClient llmClient, FactMemory factMemory,
                         EmbeddingService embeddingService,
                         com.owencli.contextos.runtime.TaskGraph taskGraph,
                         boolean useLlmScoring) {
        this.extractionEngine = new MemoryExtractionEngine(llmClient, factMemory);
        this.importanceEngine = new MemoryImportanceEngine(
                llmClient, factMemory, embeddingService, taskGraph, useLlmScoring);
        this.conflictDetector = new ConflictDetector();
        this.deduplicator = new Deduplicator();
        this.writer = new MemoryWriter(working, conversation, learnedBehavior, longTerm, episodic, semantic);
        log.info("MemoryUpdater initialized (7-type routing)");
    }

    public CompletableFuture<MemoryUpdateResult> updateFromTask(TaskSpec task, String response, EvalMetrics metrics, String userId) {
        long start = System.currentTimeMillis();
        var extracted = extractionEngine.getLegacyExtractor().extract(task, response, metrics.isSuccess());

        return importanceEngine.score(extracted).thenCompose(importanceResult -> {
            double finalScore = importanceResult.getFinalScore();
            StorageTier tier = importanceResult.getStorageTier();
            boolean shouldSaveEpisodic = extracted.isSuccess();
            boolean hasKeyConcepts = !extracted.getKeyConcepts().isEmpty();

            var existingMemories = new java.util.ArrayList<String>();
            var resolved = conflictDetector.resolve(
                    new ImportanceScorer.ScoredContent(extracted, finalScore, finalScore >= 0.75),
                    existingMemories);
            boolean hasConflict = resolved.hasConflict();
            var dedupResult = deduplicator.deduplicate(resolved, existingMemories);
            boolean wasDuplicate = dedupResult.isWasDuplicate();

            CompletableFuture<Integer> factWriteFuture = extractionEngine.extractAndSave(
                    task, response, metrics.isSuccess());

            return writer.write(dedupResult, userId)
                    .thenCompose(v -> factWriteFuture)
                    .thenApply(factCount -> {
                        long elapsed = System.currentTimeMillis() - start;
                        boolean savedToLTM = (tier == StorageTier.FACT_SEMANTIC || tier == StorageTier.EPISODE_LTM) && !wasDuplicate;
                        boolean savedToEpisodic = shouldSaveEpisodic && savedToLTM;
                        boolean savedToSemantic = hasKeyConcepts && savedToLTM;

                        log.info("MemoryUpdater complete: final={:.2f} → {}, facts={}",
                                finalScore, tier.getName(), factCount);
                        return new MemoryUpdateResult(
                                importanceResult.getRuleScore(), importanceResult.getSemanticScore(),
                                importanceResult.getNoveltyScore(), importanceResult.getFactWeightScore(),
                                importanceResult.getGoalRelationScore(), finalScore, tier,
                                savedToLTM, savedToEpisodic, savedToSemantic,
                                factCount, wasDuplicate, hasConflict, elapsed);
                    });
        });
    }

    public MemoryExtractionEngine getExtractionEngine() { return extractionEngine; }
}
