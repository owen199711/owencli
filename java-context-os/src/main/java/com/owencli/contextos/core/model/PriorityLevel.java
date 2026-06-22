package com.owencli.contextos.core.model;

public enum PriorityLevel {
    LOW("low"),
    MEDIUM("medium"),
    HIGH("high"),
    CRITICAL("critical");

    private final String value;

    PriorityLevel(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public static PriorityLevel fromValue(String value) {
        for (PriorityLevel p : values()) {
            if (p.value.equals(value)) return p;
        }
        return MEDIUM;
    }
}
