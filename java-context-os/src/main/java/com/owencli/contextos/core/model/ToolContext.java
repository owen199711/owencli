package com.owencli.contextos.core.model;

import java.util.HashMap;
import java.util.Map;

public class ToolContext {
    private String name;
    private Map<String, Object> schema = new HashMap<>();
    private String permission = "readonly";
    private Map<String, Object> state = new HashMap<>();

    public ToolContext() {}

    public ToolContext(String name) {
        this.name = name;
    }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public Map<String, Object> getSchema() { return schema; }
    public void setSchema(Map<String, Object> schema) { this.schema = schema; }
    public String getPermission() { return permission; }
    public void setPermission(String permission) { this.permission = permission; }
    public Map<String, Object> getState() { return state; }
    public void setState(Map<String, Object> state) { this.state = state; }
}
