package com.owencli.contextos.core.model;

public enum MemoryType {
    WORKING("working"),
    CONVERSATION("conversation"),
    TASK("task"),
    LONG_TERM("long_term"),
    EPISODIC("episodic"),
    SEMANTIC("semantic"),
    PROCEDURAL("procedural"),
    TOOL_EXPERIENCE("tool_experience"),
    REFLECTION("reflection"),
    FACT("fact");

    private final String value;

    MemoryType(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public static MemoryType fromValue(String value) {
        for (MemoryType m : values()) {
            if (m.value.equals(value)) return m;
        }
        return WORKING;
    }
}
