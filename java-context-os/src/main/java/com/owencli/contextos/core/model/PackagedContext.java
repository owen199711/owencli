package com.owencli.contextos.core.model;

import java.util.HashMap;
import java.util.Map;

public class PackagedContext {
    private LLMProvider provider;
    private String rawPrompt;
    private Map<String, String> sections = new HashMap<>();
    private Map<String, Object> metadata = new HashMap<>();

    public LLMProvider getProvider() { return provider; }
    public void setProvider(LLMProvider provider) { this.provider = provider; }
    public String getRawPrompt() { return rawPrompt; }
    public void setRawPrompt(String rawPrompt) { this.rawPrompt = rawPrompt; }
    public Map<String, String> getSections() { return sections; }
    public void setSections(Map<String, String> sections) { this.sections = sections; }
    public Map<String, Object> getMetadata() { return metadata; }
    public void setMetadata(Map<String, Object> metadata) { this.metadata = metadata; }
}
