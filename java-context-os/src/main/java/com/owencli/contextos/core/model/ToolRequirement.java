package com.owencli.contextos.core.model;

public class ToolRequirement {
    private String name;
    private boolean required = true;
    private String permission;

    public ToolRequirement() {}

    public ToolRequirement(String name, boolean required, String permission) {
        this.name = name;
        this.required = required;
        this.permission = permission;
    }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public boolean isRequired() { return required; }
    public void setRequired(boolean required) { this.required = required; }
    public String getPermission() { return permission; }
    public void setPermission(String permission) { this.permission = permission; }
}
