package com.owencli.contextos.core.model;

public enum LLMProvider {
    CLAUDE("claude"),
    OPENAI("openai"),
    GEMINI("gemini"),
    QWEN("qwen"),
    DEEPSEEK("deepseek");

    private final String value;

    LLMProvider(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public static LLMProvider fromValue(String value) {
        for (LLMProvider p : values()) {
            if (p.value.equalsIgnoreCase(value)) return p;
        }
        return CLAUDE;
    }
}
