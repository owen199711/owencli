package com.owencli.contextos.reflection;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.model.TaskSpec;
import com.owencli.contextos.memory.ReflectionMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Reflection Engine — analyzes task outcomes and generates reflections.
 * <p>
 * Task → Reflection → Memory
 * <p>
 * After task completion, the engine identifies root causes of failures
 * and stores lessons so the agent avoids repeating mistakes.
 */
public class ReflectionEngine {

    private static final Logger log = LoggerFactory.getLogger(ReflectionEngine.class);

    private final ReflectionMemory reflectionMemory;
    private final BaseLLMClient llmClient;

    public ReflectionEngine(ReflectionMemory reflectionMemory, BaseLLMClient llmClient) {
        this.reflectionMemory = reflectionMemory;
        this.llmClient = llmClient;
        log.info("ReflectionEngine initialized");
    }

    /**
     * Analyze a completed task and generate reflections if applicable.
     */
    public CompletableFuture<Void> reflect(TaskSpec task, String response, boolean success,
                                            String errorInfo, String userId) {
        // Only reflect on non-trivial tasks
        if (task.getRawInput() == null || task.getRawInput().length() < 15) {
            return CompletableFuture.completedFuture(null);
        }

        // For failures, always reflect; for successes, reflect on complex tasks
        if (success && task.getRawInput().length() < 50) {
            return CompletableFuture.completedFuture(null);
        }

        return analyzeFailure(task, response, errorInfo)
                .thenCompose(reflection -> {
                    if (reflection == null) return CompletableFuture.completedFuture(null);

                    return reflectionMemory.addReflection(
                            task.getRawInput(),
                            success ? "success" : "failure",
                            reflection.rootCause(),
                            reflection.lesson(),
                            reflection.preventiveActions(),
                            Map.of(
                                    "intent", task.getIntent().getValue(),
                                    "error_info", errorInfo != null ? errorInfo : "",
                                    "success", success,
                                    "task_id", task.getId()
                            )
                    ).thenAccept(id -> {
                        if (id != null && !id.isEmpty()) {
                            log.info("Reflection stored: id={}, rootCause={}, lesson={}",
                                    id, truncate(reflection.rootCause(), 60), truncate(reflection.lesson(), 60));
                        }
                    });
                });
    }

    private CompletableFuture<Reflection> analyzeFailure(TaskSpec task, String response, String errorInfo) {
        // LLM-based reflection for complex failures
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
                .thenApply(llmResponse -> parseReflection(String.valueOf(llmResponse)))
                .exceptionally(e -> {
                    log.warn("LLM reflection failed, using heuristic fallback: {}", e.getMessage());
                    return heuristicReflection(task, errorInfo);
                });
    }

    private Reflection parseReflection(String text) {
        if (text == null || text.isBlank()) return null;

        String rootCause = extractField(text, "ROOT_CAUSE:");
        String lesson = extractField(text, "LESSON:");
        String actions = extractField(text, "PREVENTIVE_ACTIONS:");

        if (rootCause == null && lesson == null) return null;

        var preventiveActions = actions != null
                ? List.of(actions.split(";"))
                : List.of("Verify configuration before execution");

        return new Reflection(
                rootCause != null ? rootCause : "Unknown",
                lesson != null ? lesson : "Review logs for details",
                preventiveActions
        );
    }

    private Reflection heuristicReflection(TaskSpec task, String errorInfo) {
        String input = task.getRawInput().toLowerCase();
        String rootCause;
        String lesson;

        if (errorInfo != null && errorInfo.contains("kubectl")) {
            rootCause = "kubectl context or configuration error";
            lesson = "Always verify kubectl context and cluster access before running Kubernetes commands";
        } else if (input.contains("deploy") || input.contains("deployment")) {
            rootCause = "Deployment configuration issue";
            lesson = "Check deployment manifests, resource limits, and namespace before deploying";
        } else if (errorInfo != null && errorInfo.contains("timeout")) {
            rootCause = "Operation timed out";
            lesson = "Increase timeout or check network connectivity before retrying";
        } else if (errorInfo != null && errorInfo.contains("auth") || errorInfo != null && errorInfo.contains("permission")) {
            rootCause = "Authentication or permission error";
            lesson = "Verify credentials and permissions before executing the command";
        } else {
            rootCause = "Unhandled error during task execution";
            lesson = "Add error handling and validation before proceeding";
        }

        return new Reflection(rootCause, lesson, List.of(
                "Verify prerequisites before execution",
                "Check error logs for detailed diagnosis",
                "Consider alternative approaches"
        ));
    }

    private String extractField(String text, String prefix) {
        int start = text.indexOf(prefix);
        if (start < 0) return null;
        start += prefix.length();
        int end = text.indexOf('\n', start);
        if (end < 0) end = text.length();

        // Also check for next field
        for (var otherPrefix : List.of("ROOT_CAUSE:", "LESSON:", "PREVENTIVE_ACTIONS:")) {
            if (otherPrefix.equals(prefix)) continue;
            int nextField = text.indexOf(otherPrefix, start);
            if (nextField >= 0 && nextField < end) {
                end = nextField;
            }
        }

        return text.substring(start, end).trim();
    }

    private record Reflection(String rootCause, String lesson, List<String> preventiveActions) {}

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }
}
