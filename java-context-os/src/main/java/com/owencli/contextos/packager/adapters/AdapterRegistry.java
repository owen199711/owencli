package com.owencli.contextos.packager.adapters;

public class AdapterRegistry {
    private final java.util.Map<com.owencli.contextos.core.model.LLMProvider, BasePromptAdapter> adapters = new java.util.concurrent.ConcurrentHashMap<>();

    public AdapterRegistry() {
        register(com.owencli.contextos.core.model.LLMProvider.CLAUDE, new ClaudeAdapter());
        register(com.owencli.contextos.core.model.LLMProvider.OPENAI, new OpenAIAdapter());
        register(com.owencli.contextos.core.model.LLMProvider.DEEPSEEK, new DeepSeekAdapter());
    }

    public void register(com.owencli.contextos.core.model.LLMProvider provider, BasePromptAdapter adapter) {
        adapters.put(provider, adapter);
    }

    public BasePromptAdapter get(com.owencli.contextos.core.model.LLMProvider provider) {
        var a = adapters.get(provider);
        if (a == null) return adapters.get(com.owencli.contextos.core.model.LLMProvider.OPENAI);
        return a;
    }
}
