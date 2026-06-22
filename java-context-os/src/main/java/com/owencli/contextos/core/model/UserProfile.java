package com.owencli.contextos.core.model;

public class UserProfile {
    private String userId;
    private String role;
    private String permission = "readonly";
    private String language = "zh-CN";
    private String skillLevel = "intermediate";
    private String organization;
    private String tenant;
    private String team;

    public UserProfile() {}

    public UserProfile(String userId, String role) {
        this.userId = userId;
        this.role = role;
    }

    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    public String getRole() { return role; }
    public void setRole(String role) { this.role = role; }
    public String getPermission() { return permission; }
    public void setPermission(String permission) { this.permission = permission; }
    public String getLanguage() { return language; }
    public void setLanguage(String language) { this.language = language; }
    public String getSkillLevel() { return skillLevel; }
    public void setSkillLevel(String skillLevel) { this.skillLevel = skillLevel; }
    public String getOrganization() { return organization; }
    public void setOrganization(String organization) { this.organization = organization; }
    public String getTenant() { return tenant; }
    public void setTenant(String tenant) { this.tenant = tenant; }
    public String getTeam() { return team; }
    public void setTeam(String team) { this.team = team; }
}
