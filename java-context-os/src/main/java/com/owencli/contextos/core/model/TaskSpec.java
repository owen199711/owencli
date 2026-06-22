package com.owencli.contextos.core.model;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

public class TaskSpec {
    private String id;
    private String rawInput;
    private IntentType intent;
    private GoalType goal;
    private List<Entity> entities = new ArrayList<>();
    private Constraint constraint = new Constraint();
    private PriorityLevel priority = PriorityLevel.MEDIUM;
    private List<ToolRequirement> toolRequirements = new ArrayList<>();
    private List<KnowledgeRequirement> knowledgeRequirements = new ArrayList<>();
    private String domain;
    private double confidence = 0.0;

    public TaskSpec() {
        this.id = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getRawInput() { return rawInput; }
    public void setRawInput(String rawInput) { this.rawInput = rawInput; }
    public IntentType getIntent() { return intent; }
    public void setIntent(IntentType intent) { this.intent = intent; }
    public GoalType getGoal() { return goal; }
    public void setGoal(GoalType goal) { this.goal = goal; }
    public List<Entity> getEntities() { return entities; }
    public void setEntities(List<Entity> entities) { this.entities = entities; }
    public Constraint getConstraint() { return constraint; }
    public void setConstraint(Constraint constraint) { this.constraint = constraint; }
    public PriorityLevel getPriority() { return priority; }
    public void setPriority(PriorityLevel priority) { this.priority = priority; }
    public List<ToolRequirement> getToolRequirements() { return toolRequirements; }
    public void setToolRequirements(List<ToolRequirement> toolRequirements) { this.toolRequirements = toolRequirements; }
    public List<KnowledgeRequirement> getKnowledgeRequirements() { return knowledgeRequirements; }
    public void setKnowledgeRequirements(List<KnowledgeRequirement> knowledgeRequirements) { this.knowledgeRequirements = knowledgeRequirements; }
    public String getDomain() { return domain; }
    public void setDomain(String domain) { this.domain = domain; }
    public double getConfidence() { return confidence; }
    public void setConfidence(double confidence) { this.confidence = confidence; }
}
