package com.owencli.contextos.core.model;

import java.util.HashMap;
import java.util.Map;

public class Entity {
    private String type;
    private String value;
    private Map<String, Object> metadata = new HashMap<>();

    public Entity() {}

    public Entity(String type, String value) {
        this.type = type;
        this.value = value;
    }

    public String getType() { return type; }
    public void setType(String type) { this.type = type; }
    public String getValue() { return value; }
    public void setValue(String value) { this.value = value; }
    public Map<String, Object> getMetadata() { return metadata; }
    public void setMetadata(Map<String, Object> metadata) { this.metadata = metadata; }
}
