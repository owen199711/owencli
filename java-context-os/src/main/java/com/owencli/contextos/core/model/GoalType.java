package com.owencli.contextos.core.model;

public enum GoalType {
    FIX("fix"),
    EXPLAIN("explain"),
    GENERATE("generate"),
    SUMMARIZE("summarize"),
    COMPARE("compare"),
    REFACTOR("refactor"),
    OPTIMIZE("optimize");

    private final String value;

    GoalType(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public static GoalType fromValue(String value) {
        for (GoalType g : values()) {
            if (g.value.equals(value)) return g;
        }
        return EXPLAIN;
    }
}
