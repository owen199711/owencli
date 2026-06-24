package com.owencli.contextos.behavior;

import com.owencli.contextos.memory.LearnedBehaviorMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;

/**
 * Behavior Consolidator — promotes candidates from pool to LearnedBehaviorMemory.
 * <p>
 * Triggered periodically or when candidates are ready.
 * Writes consolidated behaviors with structured metadata (confidence, count, success_rate).
 */
public class BehaviorConsolidator {

    private static final Logger log = LoggerFactory.getLogger(BehaviorConsolidator.class);

    private final BehaviorCandidatePool pool;
    private final LearnedBehaviorMemory learnedBehavior;

    public BehaviorConsolidator(BehaviorCandidatePool pool, LearnedBehaviorMemory learnedBehavior) {
        this.pool = pool;
        this.learnedBehavior = learnedBehavior;
        log.info("BehaviorConsolidator initialized");
    }

    /**
     * Run consolidation cycle. Checks all ready candidates and writes to LearnedBehaviorMemory.
     *
     * @return Number of behaviors consolidated
     */
    public CompletableFuture<Integer> consolidate() {
        var ready = pool.getReadyCandidates();
        if (ready.isEmpty()) {
            return CompletableFuture.completedFuture(0);
        }

        var futures = ready.stream()
                .map(this::consolidateOne)
                .toArray(CompletableFuture[]::new);

        return CompletableFuture.allOf(futures)
                .thenApply(v -> {
                    int count = ready.size();
                    log.info("BehaviorConsolidator: promoted {} behaviors", count);
                    return count;
                });
    }

    private CompletableFuture<Void> consolidateOne(BehaviorCandidate candidate) {
        String typeLabel = switch (candidate.getType()) {
            case "procedure" -> "Procedure";
            case "preference" -> "Preference";
            case "tool_pattern" -> "Tool Pattern";
            case "reflection_learning" -> "Reflection Learning";
            default -> "Behavior";
        };

        String content = String.format("[%s] %s (count=%d, confidence=%.2f, successRate=%.2f)",
                typeLabel, candidate.getDescription(),
                candidate.getCount(), candidate.getConfidence(), candidate.getSuccessRate());

        // Write to LearnedBehaviorMemory as a consolidated behavior
        return learnedBehavior.recordConsolidatedBehavior(
                candidate.getType(),
                candidate.getBehaviorKey(),
                content,
                candidate.getConfidence(),
                candidate.getSuccessRate(),
                candidate.getCount()
        ).thenAccept(id -> {
            // Remove from pool after successful consolidation
            pool.remove(candidate.getBehaviorKey());
            log.info("Behavior consolidated and promoted: {} (confidence={:.2f})",
                    candidate.getBehaviorKey(), candidate.getConfidence());
        });
    }
}
