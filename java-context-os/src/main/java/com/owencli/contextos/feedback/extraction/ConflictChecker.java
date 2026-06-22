package com.owencli.contextos.feedback.extraction;

import com.owencli.contextos.feedback.extraction.RuleFactExtractor.CandidateFact;
import com.owencli.contextos.memory.FactMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;

/**
 * Conflict Checker — detects conflicts between new candidate facts and existing stored facts.
 * <p>
 * For example, if the stored fact says user.name = "张三" and a new candidate says
 * user.name = "李四", this is an UPDATE (conflict resolved by accepting newer).
 * If the stored fact says user.preferred_language = "Go" and new candidate says = "Python",
 * this is also an UPDATE (preference changed).
 */
public class ConflictChecker {

    private static final Logger log = LoggerFactory.getLogger(ConflictChecker.class);

    private final FactMemory factMemory;

    public ConflictChecker(FactMemory factMemory) {
        this.factMemory = factMemory;
        log.info("ConflictChecker initialized");
    }

    /**
     * Check candidates against existing facts.
     * Returns resolved facts with conflict resolution decisions.
     */
    public CompletableFuture<List<ResolvedFact>> check(List<CandidateFact> candidates) {
        if (candidates.isEmpty()) {
            return CompletableFuture.completedFuture(List.of());
        }

        var futures = candidates.stream()
                .map(this::resolveConflict)
                .toList();

        return CompletableFuture.allOf(futures.toArray(new CompletableFuture<?>[0]))
                .thenApply(v -> futures.stream()
                        .map(CompletableFuture::join)
                        .filter(Objects::nonNull)
                        .toList());
    }

    private CompletableFuture<ResolvedFact> resolveConflict(CandidateFact candidate) {
        return factMemory.getFact(candidate.type()).thenApply(existing -> {
            if (existing.isEmpty()) {
                // No existing fact — this is a CREATE
                return new ResolvedFact(candidate, "CREATE", null);
            }

            var existingFact = existing.get();
            String oldValue = existingFact.getCurrentValue();

            if (oldValue.equals(candidate.value())) {
                // Same value — no change needed
                return new ResolvedFact(candidate, "NO_CHANGE", oldValue);
            }

            // Value differs — this is an UPDATE
            // Higher confidence wins; if tie, the newer value wins
            if (candidate.confidence() >= existingFact.getConfidence()) {
                log.info("Conflict resolved: {} changed from '{}' to '{}' (confidence {})",
                        candidate.type(), oldValue, candidate.value(), candidate.confidence());
                return new ResolvedFact(candidate, "UPDATE", oldValue);
            } else {
                // New fact has lower confidence — keep the old value
                log.info("Conflict resolved: keeping existing '{}'={} (existing confidence {} > new {})",
                        candidate.type(), oldValue, existingFact.getConfidence(), candidate.confidence());
                return new ResolvedFact(candidate, "REJECTED_LOW_CONFIDENCE", oldValue);
            }
        });
    }

    public record ResolvedFact(CandidateFact candidate, String action, String previousValue) {
        public boolean isNewOrUpdated() {
            return "CREATE".equals(action) || "UPDATE".equals(action);
        }
    }
}
