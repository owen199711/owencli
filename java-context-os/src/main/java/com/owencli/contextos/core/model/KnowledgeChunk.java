package com.owencli.contextos.core.model;

import java.util.HashMap;
import java.util.Map;

public class KnowledgeChunk {
    private String source;
    private String content;
    private double score = 0.0;
    private Map<String, Object> metadata = new HashMap<>();

    public KnowledgeChunk() {}

    public KnowledgeChunk(String source, String content) {
        this.source = source;
        this.content = content;
    }

    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public double getScore() { return score; }
    public void setScore(double score) { this.score = score; }
    public Map<String, Object> getMetadata() { return metadata; }
    public void setMetadata(Map<String, Object> metadata) { this.metadata = metadata; }
}
