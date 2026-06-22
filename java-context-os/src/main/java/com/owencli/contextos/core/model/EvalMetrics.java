package com.owencli.contextos.core.model;

public class EvalMetrics {
    private double answerQuality = 0.0;
    private double hallucinationScore = 0.0;
    private double toolAccuracy = 0.0;
    private double latencyMs = 0.0;
    private double costUsd = 0.0;
    private boolean success = false;
    private double rewardScore = 0.0;

    public double getAnswerQuality() { return answerQuality; }
    public void setAnswerQuality(double answerQuality) { this.answerQuality = answerQuality; }
    public double getHallucinationScore() { return hallucinationScore; }
    public void setHallucinationScore(double hallucinationScore) { this.hallucinationScore = hallucinationScore; }
    public double getToolAccuracy() { return toolAccuracy; }
    public void setToolAccuracy(double toolAccuracy) { this.toolAccuracy = toolAccuracy; }
    public double getLatencyMs() { return latencyMs; }
    public void setLatencyMs(double latencyMs) { this.latencyMs = latencyMs; }
    public double getCostUsd() { return costUsd; }
    public void setCostUsd(double costUsd) { this.costUsd = costUsd; }
    public boolean isSuccess() { return success; }
    public void setSuccess(boolean success) { this.success = success; }
    public double getRewardScore() { return rewardScore; }
    public void setRewardScore(double rewardScore) { this.rewardScore = rewardScore; }
}
