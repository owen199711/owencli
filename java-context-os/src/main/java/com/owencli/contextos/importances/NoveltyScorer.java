package com.owencli.contextos.importances;

import com.owencli.contextos.memory.EmbeddingService;
import com.owencli.contextos.memory.FactMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.CompletableFuture;

/**
 * Novelty Scorer — measures whether the content is new or already known.
 * <p>
 * First time: "I like Go" → novelty = 1.0 (high value, new info)
 * Second time: "I still like Go" → novelty = 0.1 (already known)
 * <p>
 * Computes cosine similarity against existing FactMemory entries.
 * If similarity > 0.95, heavily discounts the score.
 */
public class NoveltyScorer {

    private static final Logger log = LoggerFactory.getLogger(NoveltyScorer.class);

    private final FactMemory factMemory;
    private final EmbeddingService embeddingService;

    public NoveltyScorer(FactMemory factMemory, EmbeddingService embeddingService) {
        this.factMemory = factMemory;
        this.embeddingService = embeddingService;
    }

    /**
     * Measure novelty of content against existing memory.
     *
     * @return novelty score 0.0~1.0 (1.0 = completely new)
     */
    public CompletableFuture<Double> score(String content) {
        if (content == null || content.isBlank()) {
            return CompletableFuture.completedFuture(0.0);
        }

        return embeddingService.embed(content).thenCompose(queryEmb -> {
            if (queryEmb == null || queryEmb.isEmpty()) {
                // No embedding available → assume novel
                return CompletableFuture.completedFuture(0.8);
            }

            return factMemory.getAllFacts().thenApply(facts -> {
                if (facts.isEmpty()) {
                    // No existing facts → everything is novel
                    return 1.0;
                }

                double maxSimilarity = 0.0;
                for (var fact : facts) {
                    // Compare content against both type and value
                    String factText = fact.getType() + " = " + fact.getCurrentValue();
                    var factEmb = embeddingService.embed(factText).join();
                    if (factEmb != null && !factEmb.isEmpty()) {
                        double sim = EmbeddingService.cosineSimilarity(queryEmb, factEmb);
                        if (sim > maxSimilarity) maxSimilarity = sim;
                    }
                }

                // Novelty = 1 - similarity (with penalty for near-duplicates)
                double novelty = 1.0 - maxSimilarity;
                if (maxSimilarity > 0.95) {
                    novelty = 0.05; // Near-duplicate → very low novelty
                } else if (maxSimilarity > 0.80) {
                    novelty *= 0.5; // Similar → discount
                }

                return Math.min(1.0, Math.max(0.0, novelty));
            });
        });
    }
}
