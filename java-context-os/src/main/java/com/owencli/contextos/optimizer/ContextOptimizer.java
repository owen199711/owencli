package com.owencli.contextos.optimizer;

import com.owencli.contextos.core.model.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;

/**
 * Context Optimizer — orchestrates the optimization pipeline.
 * <p>
 * Pipeline:
 * <pre>
 * Context Optimizer
 *         │
 *         ▼
 *    Noise Filter
 *         │
 *         ▼
 *   Conflict Resolver
 *         │
 *         ▼
 *    Chunk Merge
 *         │
 *         ▼
 *    Compression
 *         │
 *         ▼
 *      Budget
 *         │
 *         ▼
 *  Prompt Layout
 * </pre>
 */
public class ContextOptimizer {

    private static final Logger log = LoggerFactory.getLogger(ContextOptimizer.class);

    private final NoiseFilter noiseFilter;
    private final RelevanceRanker ranker;
    private final ChunkMerger chunkMerger;
    private final ContextCompressor compressor;
    private final TokenBudgetAllocator budget;
    private final PromptLayout promptLayout;

    public ContextOptimizer() {
        this(new RelevanceRanker(), null, new TokenBudgetAllocator());
    }

    public ContextOptimizer(RelevanceRanker ranker, ContextCompressor compressor, TokenBudgetAllocator budget) {
        this.noiseFilter = new NoiseFilter();
        this.ranker = ranker;
        this.chunkMerger = new ChunkMerger();
        this.compressor = compressor;
        this.budget = budget;
        this.promptLayout = new PromptLayout();
        log.info("ContextOptimizer initialized with full pipeline");
    }

    public CompletableFuture<OptimizedContext> optimize(UnifiedContext context, TaskSpec task) {
        log.info("Optimizing context...");

        // Step 1: Noise Filter — remove irrelevant/noisy items
        var filteredMemory = noiseFilter.filter(context.getMemory());
        context.setMemory(filteredMemory);

        // Step 2: Rank by relevance
        context.setMemory(ranker.rankMemories(context.getMemory(), 10));
        context.setKnowledge(ranker.rankKnowledge(context.getKnowledge(), 5));

        // Step 3: Chunk Merge — merge similar items
        var mergedMemory = chunkMerger.merge(context.getMemory());
        context.setMemory(mergedMemory);

        CompletableFuture<Void> compressFuture = CompletableFuture.completedFuture(null);

        // Step 4: Compress conversation
        if (context.getConversation() != null && !context.getConversation().getHistory().isEmpty()) {
            var turns = context.getConversation().getHistory().stream()
                    .map(t -> t.getRole() + ": " + t.getContent())
                    .toList();
            compressFuture = compressor.compressConversation(turns, 2000)
                    .thenAccept(compressed -> context.getConversation().setCurrentTopic(compressed));
        }

        return compressFuture.thenApply(v -> {
            // Step 5: Allocate budget
            if (task != null && task.getConstraint().getMaxTokens() != null) {
                budget.adjustForModel(task.getConstraint().getMaxTokens());
            }
            var tokenBudget = budget.allocate();

            var optimized = new OptimizedContext();
            optimized.setCompressed(true);
            optimized.setTokenUsage(tokenBudget);
            optimized.setContext(context);

            log.info("Optimization complete: memories={} (after noise+merge), knowledge={}, budget={}",
                    context.getMemory().size(), context.getKnowledge().size(), tokenBudget.getTotal());
            return optimized;
        });
    }

    /**
     * Get the PromptLayout used by this optimizer.
     */
    public PromptLayout getPromptLayout() { return promptLayout; }
}
