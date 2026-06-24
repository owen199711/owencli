package com.owencli.contextos.core.model;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * Fact Record — a structured, versioned user fact.
 * <p>
 * Unlike append-only memory, FactRecord tracks current_value + history
 * so the agent always reads the latest truth.
 * <p>
 * Fact types include: user.name, user.preferred_language, user.occupation,
 * user.company, user.location, user.knowledge, user.preference,
 * user.behavior, user.goal, user.correction.
 */
public class FactRecord {

    // ── Fact type constants ──
    public static final String TYPE_NAME = "user.name";
    public static final String TYPE_LANGUAGE = "user.preferred_language";
    public static final String TYPE_PLATFORM = "user.preferred_platform";
    public static final String TYPE_OCCUPATION = "user.occupation";
    public static final String TYPE_COMPANY = "user.company";
    public static final String TYPE_LOCATION = "user.location";
    public static final String TYPE_SKILL = "user.skill";
    public static final String TYPE_PREFERENCE = "user.preference";
    public static final String TYPE_KNOWLEDGE = "user.knowledge";
    public static final String TYPE_BEHAVIOR = "user.behavior";
    public static final String TYPE_GOAL = "user.goal";
    public static final String TYPE_CORRECTION = "user.correction";

    public static final List<String> ALL_TYPES = List.of(
            TYPE_NAME, TYPE_LANGUAGE, TYPE_PLATFORM, TYPE_OCCUPATION,
            TYPE_COMPANY, TYPE_LOCATION, TYPE_SKILL, TYPE_PREFERENCE,
            TYPE_KNOWLEDGE, TYPE_BEHAVIOR, TYPE_GOAL, TYPE_CORRECTION
    );

    private String id;
    private String type;
    private String currentValue;
    private List<String> history;
    private double confidence;
    private String status;          // ACTIVE, ARCHIVED, SUPERSEDED
    private String source;          // e.g. "rule:我叫(.+)", "llm", "correction_signal"
    private String sourceError;     // only for correction type — records the mistake
    private Instant createdAt;
    private Instant updatedAt;

    public FactRecord() {
        this.id = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        this.history = new ArrayList<>();
        this.status = "ACTIVE";
        this.confidence = 0.8;
        this.createdAt = Instant.now();
        this.updatedAt = Instant.now();
    }

    public FactRecord(String type, String value) {
        this();
        this.type = type;
        this.currentValue = value;
        this.history.add(value);
    }

    public void update(String newValue, double newConfidence, String source) {
        if (currentValue != null && !currentValue.equals(newValue)) {
            history.add(currentValue);
        }
        this.currentValue = newValue;
        this.confidence = newConfidence;
        this.source = source;
        this.updatedAt = Instant.now();
    }

    public boolean isActive() { return "ACTIVE".equals(status); }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
    public String getCurrentValue() { return currentValue; }
    public void setCurrentValue(String currentValue) { this.currentValue = currentValue; }
    public List<String> getHistory() { return history; }
    public void setHistory(List<String> history) { this.history = history; }
    public double getConfidence() { return confidence; }
    public void setConfidence(double confidence) { this.confidence = confidence; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }
    public String getSourceError() { return sourceError; }
    public void setSourceError(String sourceError) { this.sourceError = sourceError; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Instant updatedAt) { this.updatedAt = updatedAt; }
}
