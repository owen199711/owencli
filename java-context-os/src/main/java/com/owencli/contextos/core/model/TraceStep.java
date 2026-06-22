package com.owencli.contextos.core.model;

public class TraceStep {
    private String stepName;
    private double durationMs;
    private String inputPreview;
    private String outputPreview;
    private Integer tokenCount;

    public TraceStep() {}

    public TraceStep(String stepName) {
        this.stepName = stepName;
    }

    public String getStepName() { return stepName; }
    public void setStepName(String stepName) { this.stepName = stepName; }
    public double getDurationMs() { return durationMs; }
    public void setDurationMs(double durationMs) { this.durationMs = durationMs; }
    public String getInputPreview() { return inputPreview; }
    public void setInputPreview(String inputPreview) { this.inputPreview = inputPreview; }
    public String getOutputPreview() { return outputPreview; }
    public void setOutputPreview(String outputPreview) { this.outputPreview = outputPreview; }
    public Integer getTokenCount() { return tokenCount; }
    public void setTokenCount(Integer tokenCount) { this.tokenCount = tokenCount; }
}
