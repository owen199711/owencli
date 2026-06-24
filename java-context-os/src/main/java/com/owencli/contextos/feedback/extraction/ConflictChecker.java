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

    private static final double MIN_ACCEPTABLE_CONFIDENCE = 0.3;

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

            // Same type, different value — newer information supersedes older.
            //
            // FactRecord.update() already preserves the old value in history[],
            // so there is no data loss — the version chain is always intact.
            //
            // DO NOT compare against old confidence: a career change from
            // "Java开发工程师" (rule-matched, 0.95) to "Go开发工程师"
            // (LLM-extracted, 0.85) is still a valid update. The old fact's
            // high confidence doesn't make the new information wrong.
            //
            // The minimum confidence check below is only a sanity guard
            // against garbage data (e.g. a malformed LLM response).
            if (candidate.confidence() < MIN_ACCEPTABLE_CONFIDENCE) {
                log.info("Conflict resolved: rejecting '{}'={} (confidence {:.2f} < min {:.2f})",
                        candidate.type(), candidate.value(), candidate.confidence(),
                        MIN_ACCEPTABLE_CONFIDENCE);
                return new ResolvedFact(candidate, "REJECTED_LOW_CONFIDENCE", oldValue);
            }

            log.info("Conflict resolved: {} updated from '{}' to '{}' (old confidence {:.2f}, new {:.2f})",
                    candidate.type(), oldValue, candidate.value(),
                    existingFact.getConfidence(), candidate.confidence());
            return new ResolvedFact(candidate, "UPDATE", oldValue);
        });
    }

    public record ResolvedFact(CandidateFact candidate, String action, String previousValue) {
        public boolean isNewOrUpdated() {
            return "CREATE".equals(action) || "UPDATE".equals(action);
        }
    }
}
