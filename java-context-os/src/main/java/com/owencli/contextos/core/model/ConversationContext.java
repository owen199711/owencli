package com.owencli.contextos.core.model;

import java.util.ArrayList;
import java.util.List;

public class ConversationContext {
    private List<ConversationTurn> history = new ArrayList<>();
    private String currentTopic;
    private String currentStep;
    private Integer totalSteps;
    private String status = "idle";
    private List<String> taskGraph = new ArrayList<>();

    public List<ConversationTurn> getHistory() { return history; }
    public void setHistory(List<ConversationTurn> history) { this.history = history; }
    public String getCurrentTopic() { return currentTopic; }
    public void setCurrentTopic(String currentTopic) { this.currentTopic = currentTopic; }
    public String getCurrentStep() { return currentStep; }
    public void setCurrentStep(String currentStep) { this.currentStep = currentStep; }
    public Integer getTotalSteps() { return totalSteps; }
    public void setTotalSteps(Integer totalSteps) { this.totalSteps = totalSteps; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public List<String> getTaskGraph() { return taskGraph; }
    public void setTaskGraph(List<String> taskGraph) { this.taskGraph = taskGraph; }

    public void addTurn(String role, String content) {
        this.history.add(new ConversationTurn(role, content));
    }
}
