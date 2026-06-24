package com.owencli.contextos.feedback;

import com.owencli.contextos.feedback.Deduplicator.DeduplicationResult;
import com.owencli.contextos.memory.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Memory Writer — writes processed content to appropriate memory stores.
 * <p>
 * Routing:
 *   Working       ✅ Always
 *   Conversation  ✅ Always (TTL managed by store)
 *   LearnedBehav  ✅ Always (tool execs, procedures, reflections)
 *   Episodic      ✅ On success
 *   LongTerm      ✅ On importance > 0.75, no duplicate
 *   Semantic      ✅ On important + has concepts
 *   Fact          Handled by MemoryExtractionEngine separately
 */
public class MemoryWriter {

    private static final Logger log = LoggerFactory.getLogger(MemoryWriter.class);

    private final WorkingMemory working;
    private final ConversationMemory conversation;
    private final LearnedBehaviorMemory learnedBehavior;
    private final LongTermMemory longTerm;
    private final EpisodicMemory episodic;
    private final SemanticMemory semantic;

    public MemoryWriter(WorkingMemory working, ConversationMemory conversation,
                        LearnedBehaviorMemory learnedBehavior,
                        LongTermMemory longTerm, EpisodicMemory episodic,
                        SemanticMemory semantic) {
        this.working = working;
        this.conversation = conversation;
        this.learnedBehavior = learnedBehavior;
        this.longTerm = longTerm;
        this.episodic = episodic;
        this.semantic = semantic;
        log.info("MemoryWriter initialized (7-type routing)");
    }

    public CompletableFuture<Void> write(DeduplicationResult dedupResult, String userId) {
        var extracted = dedupResult.getResolved().getScored().getExtracted();
        var scored = dedupResult.getResolved().getScored();

        // 1. Working Memory (always)
        CompletableFuture<Void> wmFuture = CompletableFuture.runAsync(() -> {
            try {
                working.push("User: " + extracted.getInput() + "\nAssistant: " + truncate(extracted.getResponse(), 500),
                        Map.of("task_id", extracted.getIntent(), "role", "conversation"));
            } catch (Exception e) { log.warn("WM write failed: {}", e.getMessage()); }
        });

        // 2. Conversation Memory (always)
        CompletableFuture<Void> convFuture = conversation.addTurn("user", extracted.getInput())
                .thenCompose(v -> conversation.addTurn("assistant", truncate(extracted.getResponse(), 5000)))
                .thenAccept(v -> {});

        // 3. Learned Behavior: record task as a procedure trace
        CompletableFuture<Void> lbFuture = learnedBehavior.recordProcedure(
                extracted.getIntent(),
                truncate(extracted.getInput(), 80) + " → " + truncate(extracted.getResponse(), 120),
                extracted.getIntent()
        ).thenAccept(v -> {});

        // 4. LongTerm Memory (only important, non-duplicate)
        CompletableFuture<Void> ltmFuture = CompletableFuture.completedFuture(null);
        if (scored.isShouldSave() && !dedupResult.isWasDuplicate()) {
            String concise = "[" + extracted.getIntent() + "] "
                    + truncate(extracted.getInput(), 80) + " → "
                    + truncate(extracted.getResponse(), 120);
            ltmFuture = longTerm.save(concise, "long_term", Map.of(
                    "category", "task_resolution",
                    "intent", extracted.getIntent(),
                    "success", extracted.isSuccess(),
                    "importance_score", scored.getScore()
            ), null, userId).thenAccept(id -> {});
        }

        // 5. Episodic Memory (on success)
        CompletableFuture<Void> epFuture = CompletableFuture.completedFuture(null);
        if (extracted.isSuccess()) {
            epFuture = episodic.recordSuccess(
                    "User requested: " + truncate(extracted.getInput(), 100),
                    "Agent responded with " + extracted.getIntent() + " intent",
                    truncate(extracted.getResponse(), 200),
                    java.util.List.of(extracted.getIntent(), "auto_logged"), null)
                    .thenAccept(id -> {});
        }

        // 6. Semantic Memory (important + has concepts)
        CompletableFuture<Void> semFuture = CompletableFuture.completedFuture(null);
        if (!extracted.getKeyConcepts().isEmpty() && scored.isShouldSave()) {
            semFuture = CompletableFuture.allOf(
                    extracted.getKeyConcepts().entrySet().stream()
                            .map(entry -> semantic.addConcept(entry.getValue(),
                                    Map.of("source", "MemoryWriter", "type", entry.getKey()),
                                    null, scored.getScore()))
                            .toArray(CompletableFuture[]::new)
            ).thenAccept(v -> {});
        }

        return CompletableFuture.allOf(wmFuture, convFuture, lbFuture, ltmFuture, epFuture, semFuture)
                .thenAccept(v -> log.info("MemoryWriter: write complete (important={}, saveLTM={}, duplicate={})",
                        extracted.isImportant(), scored.isShouldSave(), dedupResult.isWasDuplicate()));
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }
}
