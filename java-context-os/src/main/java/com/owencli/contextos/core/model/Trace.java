package com.owencli.contextos.core.model;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

public class Trace {
    private String id;
    private String taskId;
    private String rawInput;
    private List<TraceStep> steps = new ArrayList<>();
    private double totalLatencyMs = 0.0;
    private int totalTokens = 0;
    private boolean success = false;
    private Double rewardScore;
    private Instant createdAt = Instant.now();

    public Trace() { this.id = UUID.randomUUID().toString().replace("-", ""); }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getTaskId() { return taskId; }
    public void setTaskId(String taskId) { this.taskId = taskId; }
    public String getRawInput() { return rawInput; }
    public void setRawInput(String rawInput) { this.rawInput = rawInput; }
    public List<TraceStep> getSteps() { return steps; }
    public void setSteps(List<TraceStep> steps) { this.steps = steps; }
    public double getTotalLatencyMs() { return totalLatencyMs; }
    public void setTotalLatencyMs(double totalLatencyMs) { this.totalLatencyMs = totalLatencyMs; }
    public int getTotalTokens() { return totalTokens; }
    public void setTotalTokens(int totalTokens) { this.totalTokens = totalTokens; }
    public boolean isSuccess() { return success; }
    public void setSuccess(boolean success) { this.success = success; }
    public Double getRewardScore() { return rewardScore; }
    public void setRewardScore(Double rewardScore) { this.rewardScore = rewardScore; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
}
