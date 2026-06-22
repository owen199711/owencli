package com.owencli.contextos.core.model;

import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public class MemoryItem {
    private String id;
    private MemoryType type;
    private String content;
    private List<Double> embedding;
    private Instant timestamp = Instant.now();
    private int accessCount = 0;
    private double relevanceScore = 0.0;
    private Map<String, Object> metadata = new HashMap<>();

    public MemoryItem() {
        this.id = UUID.randomUUID().toString().replace("-", "");
    }

    public MemoryItem(MemoryType type, String content) {
        this();
        this.type = type;
        this.content = content;
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public MemoryType getType() { return type; }
    public void setType(MemoryType type) { this.type = type; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public List<Double> getEmbedding() { return embedding; }
    public void setEmbedding(List<Double> embedding) { this.embedding = embedding; }
    public Instant getTimestamp() { return timestamp; }
    public void setTimestamp(Instant timestamp) { this.timestamp = timestamp; }
    public int getAccessCount() { return accessCount; }
    public void setAccessCount(int accessCount) { this.accessCount = accessCount; }
    public double getRelevanceScore() { return relevanceScore; }
    public void setRelevanceScore(double relevanceScore) { this.relevanceScore = relevanceScore; }
    public Map<String, Object> getMetadata() { return metadata; }
    public void setMetadata(Map<String, Object> metadata) { this.metadata = metadata; }
}
