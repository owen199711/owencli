package com.owencli.contextos.importances;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.feedback.MemoryExtractor;
import com.owencli.contextos.memory.EmbeddingService;
import com.owencli.contextos.memory.FactMemory;
import com.owencli.contextos.runtime.TaskGraph;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;

/**
 * Memory Importance Engine — multi-dimensional scoring pipeline.
 * <p>
 * Final Score = 0.20×Rule + 0.35×Semantic + 0.20×Novelty + 0.15×FactWeight + 0.10×GoalRelation
 * <p>
 * Architecture:
 * <pre>
 *  Memory Candidate
 *         │
 *         ▼
 *  Memory Importance Engine
 *         │
 *  ┌──────┼────────────┐
 *  ▼      ▼            ▼
 * Rule  Semantic     User
 * Score  Score      Profile
 *         │
 *         ▼
 *  Final Score
 *         │
 *         ▼
 *  TieredStoragePolicy
 * </pre>
 */
public class MemoryImportanceEngine {

    private static final Logger log = LoggerFactory.getLogger(MemoryImportanceEngine.class);

    private final RuleScorer ruleScorer;
    private final SemanticScorer semanticScorer;
    private final NoveltyScorer noveltyScorer;
    private final FactWeightScorer factWeightScorer;
    private final GoalRelationScorer goalRelationScorer;

    private final boolean useLlmScoring;

    public MemoryImportanceEngine(BaseLLMClient llmClient, FactMemory factMemory,
                                   EmbeddingService embeddingService, TaskGraph taskGraph,
                                   boolean useLlmScoring) {
        this.ruleScorer = new RuleScorer();
        this.semanticScorer = new SemanticScorer(llmClient);
        this.noveltyScorer = new NoveltyScorer(factMemory, embeddingService);
        this.factWeightScorer = new FactWeightScorer();
        this.goalRelationScorer = new GoalRelationScorer(taskGraph);
        this.useLlmScoring = useLlmScoring;
        log.info("MemoryImportanceEngine initialized (useLlmScoring={})", useLlmScoring);
    }

    /**
     * Run the full multi-dimensional scoring pipeline.
     *
     * @param extracted The extracted content from MemoryExtractor
     * @return MemoryImportanceResult with all dimension scores
     */
    public CompletableFuture<MemoryImportanceResult> score(MemoryExtractor.ExtractedContent extracted) {
        String input = extracted.getInput() != null ? extracted.getInput() : "";

        // ── Dimension 1: Rule Score (fast, no LLM) ──
        double ruleScore = ruleScorer.score(extracted);

        // ── Dimension 2: Fact Weight ──
        double factWeightScore = factWeightScorer.score(input);

        // ── Dimension 3: Goal Relation ──
        double goalRelationScore = goalRelationScorer.score(input);

        // ── Dimension 4: Semantic Score (LLM) ──
        CompletableFuture<Double> semanticFuture;
        if (useLlmScoring) {
            semanticFuture = semanticScorer.score(input);
        } else {
            // Fallback: use rule score as semantic proxy
            semanticFuture = CompletableFuture.completedFuture(ruleScore * 0.7 + factWeightScore * 0.3);
        }

        // ── Dimension 5: Novelty Score (vector comparison) ──
        CompletableFuture<Double> noveltyFuture = noveltyScorer.score(input);

        return semanticFuture.thenCombine(noveltyFuture, (semanticScore, noveltyScore) -> {
            var result = new MemoryImportanceResult(
                    ruleScore, semanticScore, noveltyScore,
                    factWeightScore, goalRelationScore,
                    0.0, 0.0, 0.0, 0.0,
                    formatSummary(input, ruleScore, semanticScore, noveltyScore,
                            factWeightScore, goalRelationScore)
            );

            log.debug("Importance scores: rule={:.2f}, sem={:.2f}, nov={:.2f}, fact={:.2f}, goal={:.2f} → final={:.2f} → {}",
                    ruleScore, semanticScore, noveltyScore, factWeightScore,
                    goalRelationScore, result.getFinalScore(), result.getStorageTier().getName());

            return result;
        });
    }

    private String formatSummary(String input, double rule, double semantic,
                                  double novelty, double factWeight, double goal) {
        return String.format(
                "规则=%.2f 语义=%.2f 新颖=%.2f 事实=%.2f 目标=%.2f",
                rule, semantic, novelty, factWeight, goal
        );
    }
}
