package com.owencli.contextos.feedback;

import com.owencli.contextos.feedback.Deduplicator.DeduplicationResult;
import com.owencli.contextos.memory.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Memory Writer — final step in the MemoryUpdater pipeline.
 * Writes processed content to the appropriate memory stores based on importance and type.
 */
public class MemoryWriter {

    private static final Logger log = LoggerFactory.getLogger(MemoryWriter.class);

    private final WorkingMemory working;
    private final ConversationMemory conversation;
    private final TaskMemory task;
    private final LongTermMemory longTerm;
    private final EpisodicMemory episodic;
    private final SemanticMemory semantic;

    public MemoryWriter(WorkingMemory working, ConversationMemory conversation,
                        TaskMemory task, LongTermMemory longTerm,
                        EpisodicMemory episodic, SemanticMemory semantic) {
        this.working = working;
        this.conversation = conversation;
        this.task = task;
        this.longTerm = longTerm;
        this.episodic = episodic;
        this.semantic = semantic;
        log.info("MemoryWriter initialized");
    }

    public CompletableFuture<Void> write(DeduplicationResult dedupResult, String userId) {
        var extracted = dedupResult.getResolved().getScored().getExtracted();
        var scored = dedupResult.getResolved().getScored();

        // 1. Always write to Working Memory (active session)
        CompletableFuture<Void> wmFuture = CompletableFuture.runAsync(() -> {
            try {
                working.push("User: " + extracted.getInput() + "\nAssistant: " + truncate(extracted.getResponse(), 500),
                        Map.of("task_id", extracted.getIntent(), "role", "conversation"));
            } catch (Exception e) {
                log.warn("WM write failed: {}", e.getMessage());
            }
        });

        // 2. Always write to Conversation Memory (session history)
        CompletableFuture<Void> convFuture = conversation.addTurn("user", extracted.getInput())
                .thenCompose(v -> conversation.addTurn("assistant", truncate(extracted.getResponse(), 5000)))
                .thenAccept(v -> {});

        // 3. Always write to Task Memory
        CompletableFuture<Void> taskFuture = task.recordTask(
                extracted.getIntent(),
                truncate(extracted.getInput(), 100),
                extracted.getIntent(),
                extracted.isSuccess() ? "completed" : "failed",
                Map.of("response_length", extracted.getResponse() != null ? extracted.getResponse().length() : 0)
        ).thenAccept(v -> {});

        // 4. Only write important items to LTM
        CompletableFuture<Void> ltmFuture = CompletableFuture.completedFuture(null);
        if (scored.isShouldSave() && !dedupResult.isWasDuplicate()) {
            String conciseSummary = "[" + extracted.getIntent() + "] "
                    + truncate(extracted.getInput(), 80) + " → "
                    + truncate(extracted.getResponse(), 120);
            ltmFuture = longTerm.save(conciseSummary, "long_term", Map.of(
                    "category", "task_resolution",
                    "intent", extracted.getIntent(),
                    "success", extracted.isSuccess(),
                    "importance_score", scored.getScore()
            ), null, userId).thenAccept(id -> {});
        }

        // 5. Record successful episodes
        CompletableFuture<Void> epFuture = CompletableFuture.completedFuture(null);
        if (extracted.isSuccess()) {
            epFuture = episodic.recordSuccess(
                    "User requested: " + truncate(extracted.getInput(), 100),
                    "Agent responded with " + extracted.getIntent() + " intent",
                    truncate(extracted.getResponse(), 200),
                    java.util.List.of(extracted.getIntent(), "auto_logged"), null)
                    .thenAccept(id -> {});
        }

        // 6. Semantic: extract concepts from important content
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

        return CompletableFuture.allOf(wmFuture, convFuture, taskFuture, ltmFuture, epFuture, semFuture)
                .thenAccept(v -> log.info("MemoryWriter: write complete (important={}, saveLTM={}, duplicate={})",
                        extracted.isImportant(), scored.isShouldSave(), dedupResult.isWasDuplicate()));
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }
}
