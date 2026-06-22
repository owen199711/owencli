package com.owencli.contextos.core.model;

public enum IntentType {
    QA("qa"),
    CODING("coding"),
    PLANNING("planning"),
    DEBUGGING("debugging"),
    SEARCH("search"),
    WORKFLOW("workflow"),
    AGENT("agent"),
    DATA_ANALYSIS("data_analysis");

    private final String value;

    IntentType(String value) { this.value = value; }

    public String getValue() { return value; }

    public static IntentType fromValue(String value) {
        for (IntentType t : values()) {
            if (t.value.equals(value)) return t;
        }
        return QA;
    }
}
