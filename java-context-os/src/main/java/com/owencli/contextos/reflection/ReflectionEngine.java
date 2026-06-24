package com.owencli.contextos.reflection;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.model.TaskSpec;
import com.owencli.contextos.memory.LearnedBehaviorMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.CompletableFuture;

/**
 * Reflection Engine — analyzes task outcomes and generates reflections.
 * <p>
 * Writes reflections to LearnedBehaviorMemory (type="learned_behavior", subtype="reflection").
 */
public class ReflectionEngine {

    private static final Logger log = LoggerFactory.getLogger(ReflectionEngine.class);

    private final LearnedBehaviorMemory learnedBehavior;
    private final BaseLLMClient llmClient;

    public ReflectionEngine(LearnedBehaviorMemory learnedBehavior, BaseLLMClient llmClient) {
        this.learnedBehavior = learnedBehavior;
        this.llmClient = llmClient;
        log.info("ReflectionEngine initialized (LearnedBehaviorMemory backend)");
    }

    public CompletableFuture<Void> reflect(TaskSpec task, String response, boolean success,
                                            String errorInfo, String userId) {
        if (task.getRawInput() == null || task.getRawInput().length() < 15) {
            return CompletableFuture.completedFuture(null);
        }
        if (success && task.getRawInput().length() < 50) {
            return CompletableFuture.completedFuture(null);
        }

        return analyzeFailure(task, response, errorInfo)
                .thenCompose(reflection -> {
                    if (reflection == null) return CompletableFuture.completedFuture(null);

                    return learnedBehavior.recordReflection(
                            truncate(task.getRawInput(), 80),
                            success ? "success" : "failure",
                            reflection.rootCause(),
                            reflection.lesson(),
                            reflection.preventiveActions()
                    ).thenAccept(id -> {
                        if (id != null && !id.isEmpty()) {
                            log.info("Reflection stored in LearnedBehavior: id={}, rootCause={}, lesson={}",
                                    id, truncate(reflection.rootCause(), 60), truncate(reflection.lesson(), 60));
                        }
                    });
                });
    }

    private CompletableFuture<Reflection> analyzeFailure(TaskSpec task, String response, String errorInfo) {
        String prompt = String.format(
                "Analyze this agent task execution and provide a structured reflection.\n\n" +
                        "Task: %s\n" +
                        "Intent: %s\n" +
                        "Response: %s\n" +
                        "Error Info: %s\n\n" +
                        "Provide your analysis in this format:\n" +
                        "ROOT_CAUSE: <what went wrong>\n" +
                        "LESSON: <what to do differently next time>\n" +
                        "PREVENTIVE_ACTIONS: <action1; action2; action3>",
                task.getRawInput(), task.getIntent().getValue(),
                truncate(response, 500), errorInfo != null ? errorInfo : "none"
        );

        return llmClient.complete(prompt)
                .thenApply(r -> parseReflection(String.valueOf(r)))
                .exceptionally(e -> {
                    log.warn("Reflection analysis failed: {}", e.getMessage());
                    return null;
                });
    }

    private Reflection parseReflection(String text) {
        if (text == null || text.isBlank()) return null;
        String rootCause = extractAfter(text, "ROOT_CAUSE:");
        String lesson = extractAfter(text, "LESSON:");
        String preventiveRaw = extractAfter(text, "PREVENTIVE_ACTIONS:");
        var preventiveActions = preventiveRaw != null && !preventiveRaw.isEmpty()
                ? java.util.Arrays.asList(preventiveRaw.split(";"))
                : List.<String>of();
        if (rootCause == null && lesson == null) return null;
        return new Reflection(rootCause != null ? rootCause : "unknown",
                lesson != null ? lesson : "no lesson", preventiveActions);
    }

    private static String extractAfter(String text, String marker) {
        int idx = text.indexOf(marker);
        if (idx < 0) return null;
        int start = idx + marker.length();
        // Find next marker or end
        int end = text.length();
        for (var m : List.of("ROOT_CAUSE:", "LESSON:", "PREVENTIVE_ACTIONS:")) {
            int ni = text.indexOf(m, start + 1);
            if (ni > start && ni < end) end = ni;
        }
        return text.substring(start, end).trim();
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }

    private record Reflection(String rootCause, String lesson, List<String> preventiveActions) {}
}
