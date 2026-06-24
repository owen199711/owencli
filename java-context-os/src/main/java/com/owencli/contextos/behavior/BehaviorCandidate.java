package com.owencli.contextos.behavior;

import java.time.Instant;
import java.util.UUID;

/**
 * Behavior Candidate — a potential behavior pattern observed across episodes.
 * <p>
 * Not immediately written to LearnedBehavior. Must accumulate enough count/confidence.
 * <pre>
 * {
 *   "behavior": "prefer_detailed_response",
 *   "count": 12,
 *   "confidence": 0.92,
 *   "lastSeen": "2026-06-24",
 *   "successRate": 0.96
 * }
 * </pre>
 */
public class BehaviorCandidate {

    private String id;
    private String type;          // procedure | preference | tool_pattern | reflection_learning
    private String behaviorKey;  // unique key like "prefer_detailed_response"
    private String description;
    private int count;
    private double confidence;
    private double successRate;
    private Instant lastSeen;
    private Instant createdAt;
    private String epEvidence;   // episode IDs as evidence

    public BehaviorCandidate() {
        this.id = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        this.count = 1;
        this.confidence = 0.0;
        this.successRate = 0.0;
        this.createdAt = Instant.now();
        this.lastSeen = Instant.now();
    }

    public BehaviorCandidate(String type, String behaviorKey, String description) {
        this();
        this.type = type;
        this.behaviorKey = behaviorKey;
        this.description = description;
    }

    /** Increment count, update confidence, recalculate success rate. */
    public void observe(boolean success) {
        this.count++;
        this.lastSeen = Instant.now();
        // Running average for success rate
        this.successRate = (this.successRate * (count - 1) + (success ? 1.0 : 0.0)) / count;
        // Confidence: sigmoid-like curve count/(count+K)
        // count=1: 0.25, count=3: 0.50, count=7: 0.70 ✓, count=15: 0.83, ∞: 1.0
        // K=3 ensures fast growth early, smooth saturation
        this.confidence = Math.min(0.95, (double) count / (count + 3));
        if (!success) this.confidence *= 0.9;
    }

    /** Apply time decay. Long-unseen behaviors lose confidence. */
    public void applyDecay() {
        long daysSinceLastSeen = java.time.Duration.between(lastSeen, Instant.now()).toDays();
        if (daysSinceLastSeen > 7) {
            this.confidence *= Math.max(0.3, 1.0 - (daysSinceLastSeen - 7) * 0.05);
        }
    }

    public boolean isReadyForConsolidation() {
        return count >= 3
                && confidence >= 0.7
                && successRate >= 0.6;
    }

    // ── Getters / Setters ──

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
    public String getBehaviorKey() { return behaviorKey; }
    public void setBehaviorKey(String behaviorKey) { this.behaviorKey = behaviorKey; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public int getCount() { return count; }
    public void setCount(int count) { this.count = count; }
    public double getConfidence() { return confidence; }
    public void setConfidence(double confidence) { this.confidence = confidence; }
    public double getSuccessRate() { return successRate; }
    public void setSuccessRate(double successRate) { this.successRate = successRate; }
    public Instant getLastSeen() { return lastSeen; }
    public void setLastSeen(Instant lastSeen) { this.lastSeen = lastSeen; }
    public Instant getCreatedAt() { return createdAt; }
    public void setCreatedAt(Instant createdAt) { this.createdAt = createdAt; }
    public String getEpEvidence() { return epEvidence; }
    public void setEpEvidence(String epEvidence) { this.epEvidence = epEvidence; }
}
