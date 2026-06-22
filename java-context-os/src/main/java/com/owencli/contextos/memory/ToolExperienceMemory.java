package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Tool Experience Memory — records agent's experience using tools.
 * Stores success rates, typical usage patterns, common errors, and recommendations.
 * Enables the agent to learn optimal tool selection from experience.
 */
public class ToolExperienceMemory {

    private static final Logger log = LoggerFactory.getLogger(ToolExperienceMemory.class);

    private final SQLiteStore store;
    private final String userId;

    public ToolExperienceMemory(SQLiteStore store, String userID) {
        this.store = store;
        this.userId = userID;
        log.info("ToolExperienceMemory initialized");
    }

    /**
     * Record a tool execution outcome.
     */
    public CompletableFuture<String> recordExecution(String toolName, String parameters,
                                                       boolean success, long durationMs,
                                                       String errorType, String scenario) {
        String memId = UUID.randomUUID().toString().replace("-", "");

        // Build enriched metadata
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("tool_name", toolName);
        metadata.put("parameters", parameters);
        metadata.put("success", success);
        metadata.put("duration_ms", durationMs);
        metadata.put("error_type", errorType != null ? errorType : "");
        metadata.put("scenario", scenario != null ? scenario : "");
        metadata.put("userId", userId);

        String content = String.format("[ToolExec] %s | params=%s | success=%s | duration=%dms | error=%s | scenario=%s",
                toolName, truncate(parameters, 100), success, durationMs,
                errorType != null ? errorType : "none", scenario != null ? scenario : "unknown");

        return store.saveMemory(memId, "tool_experience", content, null, userId, null, metadata, null);
    }

    /**
     * Retrieve tool experiences relevant to a given scenario or tool name.
     */
    public CompletableFuture<List<ToolExperience>> retrieve(String query, int topK) {
        return store.queryMemories("tool_experience", null, userId, query, null, null, topK, 0)
                .thenApply(results -> results.stream().map(this::toExperience).collect(Collectors.toList()));
    }

    /**
     * Get the best tool for a given scenario based on historical success rates.
     */
    public CompletableFuture<Optional<ToolExperience>> getBestTool(String scenario) {
        return store.queryMemories("tool_experience", null, userId, scenario, null, null, 50, 0)
                .thenApply(results -> {
                    Map<String, List<ToolExperience>> byTool = results.stream()
                            .map(this::toExperience)
                            .collect(Collectors.groupingBy(ToolExperience::getToolName));

                    return byTool.entrySet().stream()
                            .map(entry -> {
                                List<ToolExperience> exps = entry.getValue();
                                long successCount = exps.stream().filter(ToolExperience::isSuccess).count();
                                double successRate = (double) successCount / exps.size();
                                double avgDuration = exps.stream().mapToLong(ToolExperience::getDurationMs).average().orElse(0);
                                return new ToolExperienceSummary(entry.getKey(), successRate, avgDuration, exps.size());
                            })
                            .max(Comparator.comparingDouble(ToolExperienceSummary::successRate)
                                    .thenComparingDouble(s -> -s.avgDuration()))
                            .flatMap(summary -> {
                                // Return the most recent successful experience for this tool
                                return results.stream()
                                        .map(this::toExperience)
                                        .filter(e -> e.getToolName().equals(summary.toolName()) && e.isSuccess())
                                        .findFirst();
                            });
                });
    }

    /**
     * Get aggregate statistics for a tool.
     */
    public CompletableFuture<Map<String, Object>> getToolStats(String toolName) {
        return store.queryMemories("tool_experience", null, userId, toolName, null, null, 200, 0)
                .thenApply(results -> {
                    var stats = new LinkedHashMap<String, Object>();
                    var experiences = results.stream().map(this::toExperience).collect(Collectors.toList());

                    long total = experiences.size();
                    long successCount = experiences.stream().filter(ToolExperience::isSuccess).count();
                    double avgDuration = experiences.stream().mapToLong(ToolExperience::getDurationMs).average().orElse(0);

                    // Collect common errors
                    Map<String, Long> errorCounts = experiences.stream()
                            .filter(e -> e.getErrorType() != null && !e.getErrorType().isEmpty())
                            .collect(Collectors.groupingBy(ToolExperience::getErrorType, Collectors.counting()));

                    // Collect common scenarios
                    Map<String, Long> scenarioCounts = experiences.stream()
                            .filter(e -> e.getScenario() != null && !e.getScenario().isEmpty())
                            .collect(Collectors.groupingBy(ToolExperience::getScenario, Collectors.counting()));

                    stats.put("tool_name", toolName);
                    stats.put("total_executions", total);
                    stats.put("success_rate", total > 0 ? (double) successCount / total : 0.0);
                    stats.put("avg_duration_ms", avgDuration);
                    stats.put("common_errors", errorCounts);
                    stats.put("common_scenarios", scenarioCounts);

                    return stats;
                });
    }

    private ToolExperience toExperience(Map<String, Object> row) {
        String content = (String) row.getOrDefault("content", "");
        var exp = new ToolExperience();
        exp.setContent(content);
        exp.setToolName(extractField(content, "ToolExec", 1));
        exp.setSuccess(content.contains("success=true"));
        exp.setDurationMs(extractDuration(content));
        exp.setErrorType(extractErrorType(content));
        exp.setScenario(extractScenario(content));
        return exp;
    }

    private String extractField(String content, String prefix, int index) {
        try {
            if (!content.startsWith("[" + prefix + "]")) return "";
            var parts = content.split("\\|");
            if (parts.length > index) {
                var kv = parts[index].trim();
                return kv.contains("=") ? kv.split("=", 2)[1].trim() : kv;
            }
            return "";
        } catch (Exception e) {
            return "";
        }
    }

    private long extractDuration(String content) {
        try {
            var parts = content.split("\\|");
            for (var p : parts) {
                p = p.trim();
                if (p.startsWith("duration=")) {
                    return Long.parseLong(p.replace("duration=", "").replace("ms", "").trim());
                }
            }
        } catch (Exception ignored) {}
        return 0;
    }

    private String extractErrorType(String content) {
        try {
            var parts = content.split("\\|");
            for (var p : parts) {
                p = p.trim();
                if (p.startsWith("error=")) {
                    var val = p.replace("error=", "").trim();
                    return val.equals("none") ? "" : val;
                }
            }
        } catch (Exception ignored) {}
        return "";
    }

    private String extractScenario(String content) {
        try {
            var parts = content.split("\\|");
            for (var p : parts) {
                p = p.trim();
                if (p.startsWith("scenario=")) {
                    return p.replace("scenario=", "").trim();
                }
            }
        } catch (Exception ignored) {}
        return "";
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }

    // ── Inner types ──

    public static class ToolExperience {
        private String content;
        private String toolName;
        private boolean success;
        private long durationMs;
        private String errorType;
        private String scenario;

        public String getContent() { return content; }
        public void setContent(String content) { this.content = content; }
        public String getToolName() { return toolName; }
        public void setToolName(String toolName) { this.toolName = toolName; }
        public boolean isSuccess() { return success; }
        public void setSuccess(boolean success) { this.success = success; }
        public long getDurationMs() { return durationMs; }
        public void setDurationMs(long durationMs) { this.durationMs = durationMs; }
        public String getErrorType() { return errorType; }
        public void setErrorType(String errorType) { this.errorType = errorType; }
        public String getScenario() { return scenario; }
        public void setScenario(String scenario) { this.scenario = scenario; }
    }

    private record ToolExperienceSummary(String toolName, double successRate, double avgDuration, int totalExecutions) {}
}
