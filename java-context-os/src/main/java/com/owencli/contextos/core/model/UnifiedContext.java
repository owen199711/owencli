package com.owencli.contextos.core.model;

import java.util.ArrayList;
import java.util.List;

public class UnifiedContext {
    private UserProfile identity;
    private ConversationContext conversation;
    private EnvironmentContext environment;
    private List<MemoryItem> memory = new ArrayList<>();
    private List<KnowledgeChunk> knowledge = new ArrayList<>();
    private List<ToolContext> tools = new ArrayList<>();

    public UserProfile getIdentity() { return identity; }
    public void setIdentity(UserProfile identity) { this.identity = identity; }
    public ConversationContext getConversation() { return conversation; }
    public void setConversation(ConversationContext conversation) { this.conversation = conversation; }
    public EnvironmentContext getEnvironment() { return environment; }
    public void setEnvironment(EnvironmentContext environment) { this.environment = environment; }
    public List<MemoryItem> getMemory() { return memory; }
    public void setMemory(List<MemoryItem> memory) { this.memory = memory; }
    public List<KnowledgeChunk> getKnowledge() { return knowledge; }
    public void setKnowledge(List<KnowledgeChunk> knowledge) { this.knowledge = knowledge; }
    public List<ToolContext> getTools() { return tools; }
    public void setTools(List<ToolContext> tools) { this.tools = tools; }
}
