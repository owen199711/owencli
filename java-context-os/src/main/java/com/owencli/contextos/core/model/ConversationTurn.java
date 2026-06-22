package com.owencli.contextos.core.model;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

public class ConversationTurn {
    private String role; // "user" | "assistant" | "tool"
    private String content;
    private Instant timestamp = Instant.now();
    private Map<String, Object> metadata = new HashMap<>();

    public ConversationTurn() {}

    public ConversationTurn(String role, String content) {
        this.role = role;
        this.content = content;
    }

    public String getRole() { return role; }
    public void setRole(String role) { this.role = role; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public Instant getTimestamp() { return timestamp; }
    public void setTimestamp(Instant timestamp) { this.timestamp = timestamp; }
    public Map<String, Object> getMetadata() { return metadata; }
    public void setMetadata(Map<String, Object> metadata) { this.metadata = metadata; }
}
