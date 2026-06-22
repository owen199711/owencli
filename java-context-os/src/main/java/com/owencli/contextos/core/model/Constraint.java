package com.owencli.contextos.core.model;

import java.util.List;

public class Constraint {
    private Integer maxTokens;
    private Integer maxSteps;
    private Integer timeoutSeconds;
    private List<String> allowedTools;

    public Constraint() {}

    public Constraint(Integer maxTokens, Integer maxSteps, Integer timeoutSeconds, List<String> allowedTools) {
        this.maxTokens = maxTokens;
        this.maxSteps = maxSteps;
        this.timeoutSeconds = timeoutSeconds;
        this.allowedTools = allowedTools;
    }

    public Integer getMaxTokens() { return maxTokens; }
    public void setMaxTokens(Integer maxTokens) { this.maxTokens = maxTokens; }
    public Integer getMaxSteps() { return maxSteps; }
    public void setMaxSteps(Integer maxSteps) { this.maxSteps = maxSteps; }
    public Integer getTimeoutSeconds() { return timeoutSeconds; }
    public void setTimeoutSeconds(Integer timeoutSeconds) { this.timeoutSeconds = timeoutSeconds; }
    public List<String> getAllowedTools() { return allowedTools; }
    public void setAllowedTools(List<String> allowedTools) { this.allowedTools = allowedTools; }

    public static Constraint empty() { return new Constraint(null, null, null, null); }
}
