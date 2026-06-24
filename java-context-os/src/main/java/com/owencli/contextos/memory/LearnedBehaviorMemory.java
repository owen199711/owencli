package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.MemoryType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Learned Behavior Memory — merged storage for procedures and tool execution stats.
 * <p>
 * Replaces the old ProceduralMemory + ToolExperienceMemory.
 * Records "how to do X" (procedures) and "how well does the agent use tool X" (stats).
 */
public class LearnedBehaviorMemory {

    private static final Logger log = LoggerFactory.getLogger(LearnedBehaviorMemory.class);

    private final SQLiteStore store;
    private final String userId;

    public LearnedBehaviorMemory(SQLiteStore store, String userId) {
        this.store = store;
        this.userId = userId;
        log.info("LearnedBehaviorMemory initialized");
    }

    // ── Procedure recording ──

    public CompletableFuture<String> recordProcedure(String name, String steps, String domain) {
        String memId = UUID.randomUUID().toString().replace("-", "");
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("behavior_type", "procedure");
        meta.put("name", name);
        meta.put("domain", domain);
        String content = String.format("[Procedure] %s | domain=%s\n%s", name, domain, steps);
        return store.saveMemory(memId, "learned_behavior", content, null, userId, null, meta, null);
    }

    // ── Tool execution recording ──

    public CompletableFuture<String> recordToolExec(String toolName, String params,
                                                      boolean success, long durationMs,
                                                      String errorType, String scenario) {
        String memId = UUID.randomUUID().toString().replace("-", "");
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("behavior_type", "tool_exec");
        meta.put("tool_name", toolName);
        meta.put("parameters", params);
        meta.put("success", success);
        meta.put("duration_ms", durationMs);
        meta.put("error_type", errorType != null ? errorType : "");
        meta.put("scenario", scenario != null ? scenario : "");
        String content = String.format("[ToolExec] %s | success=%s | %dms | error=%s", toolName, success, durationMs, errorType != null ? errorType : "none");
        return store.saveMemory(memId, "learned_behavior", content, null, userId, null, meta, null);
    }

    /**
     * Record a consolidated behavior (promoted from BehaviorCandidatePool).
     * This is the final, stable behavior after pattern detection + consolidation.
     */
    public CompletableFuture<String> recordConsolidatedBehavior(String behaviorType, String behaviorKey,
                                                                  String content, double confidence,
                                                                  double successRate, int count) {
        String memId = UUID.randomUUID().toString().replace("-", "");
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("behavior_type", "consolidated");
        meta.put("behavior_subtype", behaviorType);
        meta.put("behavior_key", behaviorKey);
        meta.put("confidence", confidence);
        meta.put("success_rate", successRate);
        meta.put("observation_count", count);
        String formattedContent = String.format("[Consolidated %s] %s (confidence=%.2f, count=%d)",
                behaviorType, content, confidence, count);
        return store.saveMemory(memId, "learned_behavior", formattedContent, null, userId, null, meta, null);
    }

    // ── Retrieval ──

    public CompletableFuture<List<MemoryItem>> retrieveProcedures(String query, String domain, int topK) {
        return store.queryMemories("learned_behavior", null, userId, query, null, null, topK, 0)
                .thenApply(results -> results.stream()
                        .filter(r -> isProcedure(r))
                        .filter(r -> domain == null || domain.equals(getMetaString(r, "domain")))
                        .map(r -> toItem(r, "procedural"))
                        .collect(Collectors.toList()));
    }

    public CompletableFuture<List<MemoryItem>> retrieveToolExecs(String toolName, int topK) {
        return store.queryMemories("learned_behavior", null, userId, toolName, null, null, topK, 0)
                .thenApply(results -> results.stream()
                        .filter(r -> isToolExec(r))
                        .map(r -> toItem(r, "tool_exec"))
                        .collect(Collectors.toList()));
    }

    public CompletableFuture<Map<String, Object>> getToolStats(String toolName) {
        return store.queryMemories("learned_behavior", null, userId, toolName, null, null, 200, 0)
                .thenApply(results -> {
                    var execs = results.stream().filter(this::isToolExec).collect(Collectors.toList());
                    var stats = new LinkedHashMap<String, Object>();
                    long total = execs.size();
                    long successCount = execs.stream().filter(r -> "true".equals(getMetaString(r, "success"))).count();
                    stats.put("tool_name", toolName);
                    stats.put("total_executions", total);
                    stats.put("success_rate", total > 0 ? (double) successCount / total : 0.0);
                    stats.put("avg_duration_ms", execs.stream()
                            .mapToLong(r -> parseLong(getMetaString(r, "duration_ms")))
                            .average().orElse(0));
                    Map<String, Long> errors = execs.stream()
                            .map(r -> getMetaString(r, "error_type"))
                            .filter(e -> !e.isEmpty())
                            .collect(Collectors.groupingBy(e -> e, Collectors.counting()));
                    stats.put("common_errors", errors);
                    return stats;
                });
    }

    // ── Reflection recording (former ReflectionMemory) ──

    public CompletableFuture<String> recordReflection(String taskDesc, String outcome,
                                                        String rootCause, String lesson,
                                                        List<String> preventiveActions) {
        String memId = UUID.randomUUID().toString().replace("-", "");
        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("behavior_type", "reflection");
        meta.put("task", taskDesc);
        meta.put("outcome", outcome);
        meta.put("root_cause", rootCause);
        meta.put("lesson", lesson);
        meta.put("preventive_actions", preventiveActions);
        String content = String.format("[Reflection] %s | %s\nRoot Cause: %s\nLesson: %s\nPrevention: %s",
                truncate(taskDesc, 80), outcome, rootCause, lesson, String.join("; ", preventiveActions));
        return store.saveMemory(memId, "learned_behavior", content, null, userId, null, meta, null);
    }

    public CompletableFuture<List<MemoryItem>> retrieveReflections(String query, int topK) {
        return store.queryMemories("learned_behavior", null, userId, query, null, null, topK, 0)
                .thenApply(results -> results.stream()
                        .filter(r -> isReflection(r))
                        .map(r -> toItem(r, "reflection"))
                        .collect(Collectors.toList()));
    }

    // ── General retrieval (all learned behaviors) ──

    public CompletableFuture<List<MemoryItem>> retrieveAll(String query, int topK) {
        return store.queryMemories("learned_behavior", null, userId, query, null, null, topK, 0)
                .thenApply(results -> results.stream()
                        .map(r -> toItem(r, getMetaString(r, "behavior_type")))
                        .collect(Collectors.toList()));
    }

    // ── Helpers ──

    private boolean isProcedure(Map<String, Object> r) {
        return "procedure".equals(getMetaString(r, "behavior_type"));
    }

    private boolean isToolExec(Map<String, Object> r) {
        return "tool_exec".equals(getMetaString(r, "behavior_type"));
    }

    private boolean isReflection(Map<String, Object> r) {
        return "reflection".equals(getMetaString(r, "behavior_type"));
    }

    @SuppressWarnings("unchecked")
    private String getMetaString(Map<String, Object> row, String key) {
        try {
            var meta = (Map<String, Object>) row.getOrDefault("metadata", Map.of());
            Object v = meta.get(key);
            return v != null ? v.toString() : "";
        } catch (Exception e) {
            return "";
        }
    }

    private long parseLong(String s) {
        try { return Long.parseLong(s); } catch (Exception e) { return 0; }
    }

    private MemoryItem toItem(Map<String, Object> row, String subtype) {
        var item = new MemoryItem(MemoryType.LEARNED_BEHAVIOR, (String) row.getOrDefault("content", ""));
        item.setId((String) row.get("id"));
        item.setRelevanceScore(0.7);
        item.setMetadata(Map.of("behavior_subtype", subtype));
        return item;
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }
}
