package com.owencli.contextos.pipeline;
import com.owencli.contextos.core.model.*;
import com.owencli.contextos.feedback.MemoryUpdateResult;
import com.owencli.contextos.policy.ContextPolicy;
import java.util.HashMap;
import java.util.Map;

public class PipelineContext {
    private final String userInput;
    private final String sessionId;
    private final String userId;
    private final LLMProvider provider;
    private final Map<String, Object> sharedComponents;
    private TaskSpec taskSpec;
    private UnifiedContext unifiedContext;
    private OptimizedContext optimizedContext;
    private PackagedContext packagedContext;
    private ContextPolicy.PolicyDirective policyDirective;
    private String llmResponse;
    private EvalMetrics metrics;
    private MemoryUpdateResult memoryUpdateResult;
    private boolean cancelled;
    private final Map<String, Object> metadata = new HashMap<>();
    private Map<String, Object> rawResult;

    public PipelineContext(String ui, String sid, String uid, LLMProvider p, Map<String, Object> sc) {
        this.userInput = ui; this.sessionId = sid; this.userId = uid; this.provider = p;
        this.sharedComponents = sc != null ? sc : new HashMap<>();
    }

    public String userInput() { return userInput; }
    public String sessionId() { return sessionId; }
    public String userId() { return userId; }
    public LLMProvider provider() { return provider; }
    public TaskSpec taskSpec() { return taskSpec; }
    public UnifiedContext unifiedContext() { return unifiedContext; }
    public OptimizedContext optimizedContext() { return optimizedContext; }
    public PackagedContext packagedContext() { return packagedContext; }
    public ContextPolicy.PolicyDirective policyDirective() { return policyDirective; }
    public String llmResponse() { return llmResponse; }
    public EvalMetrics metrics() { return metrics; }
    public MemoryUpdateResult memoryUpdateResult() { return memoryUpdateResult; }
    public boolean isCancelled() { return cancelled; }
    public Map<String, Object> metadata() { return metadata; }
    public Map<String, Object> sharedComponents() { return sharedComponents; }
    public Map<String, Object> rawResult() { return rawResult; }
    @SuppressWarnings("unchecked")
    public <T> T getComponent(String key) { return (T) sharedComponents.get(key); }

    public void setTaskSpec(TaskSpec v) { this.taskSpec = v; }
    public void setUnifiedContext(UnifiedContext v) { this.unifiedContext = v; }
    public void setOptimizedContext(OptimizedContext v) { this.optimizedContext = v; }
    public void setPackagedContext(PackagedContext v) { this.packagedContext = v; }
    public void setPolicyDirective(ContextPolicy.PolicyDirective v) { this.policyDirective = v; }
    public void setLlmResponse(String v) { this.llmResponse = v; }
    public void setMetrics(EvalMetrics v) { this.metrics = v; }
    public void setMemoryUpdateResult(MemoryUpdateResult v) { this.memoryUpdateResult = v; }
    public void setCancelled(boolean v) { this.cancelled = v; }
    public void setRawResult(Map<String, Object> v) { this.rawResult = v; }
}
