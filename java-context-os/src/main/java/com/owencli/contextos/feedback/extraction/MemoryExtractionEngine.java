package com.owencli.contextos.feedback.extraction;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.model.TaskSpec;
import com.owencli.contextos.feedback.MemoryExtractor;
import com.owencli.contextos.feedback.extraction.ConflictChecker.ResolvedFact;
import com.owencli.contextos.memory.FactMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.CompletableFuture;

/**
 * Memory Extraction Engine — unified extraction pipeline.
 * <p>
 * Architecture:
 * <pre>
 *                Memory Extraction Engine
 *                       │
 *        ┌──────────────┼──────────────┐
 *        ▼              ▼              ▼
 *  Fact Detector   Episode Detector  Reflection Detector
 *        │              │              │
 *        ▼              ▼              ▼
 *  Preference      Task Pattern    Failure Pattern
 *        │              │              │
 *        └──────────────┼──────────────┘
 *                       ▼
 *              Memory Normalizer
 * </pre>
 * <p>
 * Fact Detector itself uses a hybrid approach:
 * <pre>
 *  User Input
 *       │
 *       ▼
 *  Rule Engine (fast path, <1ms)
 *       │
 *       ▼
 *  Matched? ──YES──→ FactValidator → ConflictChecker → FactUpdater → FactMemory
 *       │
 *       NO
 *       ▼
 *  LLM Extractor (fallback)
 *       │
 *       ▼
 *  FactValidator → ConflictChecker → FactUpdater → FactMemory
 * </pre>
 */
public class MemoryExtractionEngine {

    private static final Logger log = LoggerFactory.getLogger(MemoryExtractionEngine.class);

    private final MemoryExtractor legacyExtractor;
    private final RuleFactExtractor ruleExtractor;
    private final LLMFactExtractor llmExtractor;
    private final FactValidator validator;
    private final ConflictChecker conflictChecker;
    private final FactUpdater factUpdater;

    public MemoryExtractionEngine(BaseLLMClient llmClient, FactMemory factMemory) {
        this.legacyExtractor = new MemoryExtractor();
        this.ruleExtractor = new RuleFactExtractor();
        this.llmExtractor = new LLMFactExtractor(llmClient);
        this.validator = new FactValidator();
        this.conflictChecker = new ConflictChecker(factMemory);
        this.factUpdater = new FactUpdater(factMemory);
        log.info("MemoryExtractionEngine initialized");
    }

    /**
     * Run the full extraction pipeline.
     *
     * @return Number of facts written
     */
    public CompletableFuture<Integer> extractAndSave(TaskSpec task, String response, boolean success) {
        String input = task.getRawInput();

        // Step 1: Try Rule Engine first (fast path)
        var ruleCandidates = ruleExtractor.extract(input);

        List<RuleFactExtractor.CandidateFact> candidates;
        if (!ruleCandidates.isEmpty()) {
            candidates = ruleCandidates;
            log.info("Rule engine matched: {} = {}", candidates.get(0).type(), candidates.get(0).value());
        } else {
            // Step 2: Fallback to LLM Extractor
            return llmExtractor.extract(input).thenCompose(llmCandidates -> {
                if (llmCandidates.isEmpty()) {
                    log.debug("LLM extractor found no facts");
                    return CompletableFuture.completedFuture(0);
                }
                return processCandidates(llmCandidates, input);
            });
        }

        return processCandidates(candidates, input);
    }

    private CompletableFuture<Integer> processCandidates(List<RuleFactExtractor.CandidateFact> candidates,
                                                          String input) {
        // Step 3: Validate with signal detection (correction/reinforcement)
        var validated = validator.validate(candidates, input);
        if (validated.isEmpty()) {
            return CompletableFuture.completedFuture(0);
        }

        // Step 4: Check conflicts
        return conflictChecker.check(validated)
                .thenCompose(resolved -> {
                    var newOrUpdated = resolved.stream()
                            .filter(ResolvedFact::isNewOrUpdated)
                            .toList();
                    if (newOrUpdated.isEmpty()) {
                        log.debug("No new or updated facts after conflict check");
                        return CompletableFuture.completedFuture(0);
                    }

                    // Step 5: Write to Fact Memory (with versioning)
                    return factUpdater.apply(resolved);
                });
    }

    public MemoryExtractor getLegacyExtractor() { return legacyExtractor; }
    public FactUpdater getFactUpdater() { return factUpdater; }
}
