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
 * Example:
 * <pre>
 *   FactRecord{
 *     id = "fact_abc123",
 *     type = "user.name",
 *     currentValue = "李四",
 *     history = ["张三", "李四"],
 *     confidence = 0.98,
 *     status = ACTIVE,
 *     source = "rule:我叫张三",
 *     createdAt = ..., updatedAt = ...
 *   }
 * </pre>
 */
public class FactRecord {

    private String id;
    private String type;           // e.g. "user.name", "user.preferred_language", "user.occupation"
    private String currentValue;   // the current value (always the latest truth)
    private List<String> history;  // full change history
    private double confidence;     // 0.0 - 1.0
    private String status;         // ACTIVE, ARCHIVED, SUPERSEDED
    private String source;         // e.g. "rule:我叫(.+)", "llm", "manual"
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

    /**
     * Update this fact with a new value. The old value moves to history.
     */
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

    // ── Getters / Setters ──

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
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Instant updatedAt) { this.updatedAt = updatedAt; }
}
