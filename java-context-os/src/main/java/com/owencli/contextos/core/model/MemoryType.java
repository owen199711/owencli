package com.owencli.contextos.core.model;

public enum MemoryType {
    WORKING("working"),
    CONVERSATION("conversation"),
    EPISODIC("episodic"),
    SEMANTIC("semantic"),
    FACT("fact"),
    LEARNED_BEHAVIOR("learned_behavior"),
    LONG_TERM("long_term");

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
