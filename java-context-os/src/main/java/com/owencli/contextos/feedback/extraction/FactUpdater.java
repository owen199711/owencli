package com.owencli.contextos.feedback.extraction;

import com.owencli.contextos.feedback.extraction.ConflictChecker.ResolvedFact;
import com.owencli.contextos.memory.FactMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.CompletableFuture;

/**
 * Fact Updater — applies resolved facts to Fact Memory with versioning.
 * <p>
 * Only CREATE and UPDATE actions are applied.
 * Each update preserves the previous value in the history.
 */
public class FactUpdater {

    private static final Logger log = LoggerFactory.getLogger(FactUpdater.class);

    private final FactMemory factMemory;

    public FactUpdater(FactMemory factMemory) {
        this.factMemory = factMemory;
        log.info("FactUpdater initialized");
    }

    /**
     * Apply resolved facts to Fact Memory.
     *
     * @return Number of facts actually written
     */
    public CompletableFuture<Integer> apply(List<ResolvedFact> resolved) {
        var writeable = resolved.stream()
                .filter(ResolvedFact::isNewOrUpdated)
                .toList();

        if (writeable.isEmpty()) {
            log.debug("FactUpdater: no facts to write");
            return CompletableFuture.completedFuture(0);
        }

        var futures = writeable.stream()
                .map(r -> factMemory.setFact(
                        r.candidate().type(),
                        r.candidate().value(),
                        r.candidate().confidence(),
                        r.candidate().source()
                ))
                .toList();

        return CompletableFuture.allOf(futures.toArray(new CompletableFuture<?>[0]))
                .thenApply(v -> {
                    for (var r : writeable) {
                        String action = r.action().equals("UPDATE") ? "updated" : "created";
                        log.info("Fact {}: {} = {} (from {})", action,
                                r.candidate().type(), r.candidate().value(), r.candidate().source());
                    }
                    return writeable.size();
                });
    }
}
