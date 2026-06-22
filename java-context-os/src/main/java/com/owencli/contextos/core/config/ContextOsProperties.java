package com.owencli.contextos.core.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Component
@ConfigurationProperties(prefix = "context-os")
public class ContextOsProperties {

    private Llm llm = new Llm();
    private Embedding embedding = new Embedding();
    private Memory memory = new Memory();
    private Trace trace = new Trace();

    public Llm getLlm() { return llm; }
    public void setLlm(Llm llm) { this.llm = llm; }
    public Embedding getEmbedding() { return embedding; }
    public void setEmbedding(Embedding embedding) { this.embedding = embedding; }
    public Memory getMemory() { return memory; }
    public void setMemory(Memory memory) { this.memory = memory; }
    public Trace getTrace() { return trace; }
    public void setTrace(Trace trace) { this.trace = trace; }

    // ── LLM ──

    public static class Llm {
        private String provider = "deepseek";
        private DeepSeek deepseek = new DeepSeek();
        private Anthropic anthropic = new Anthropic();
        private OpenAi openai = new OpenAi();

        public String getProvider() { return provider; }
        public void setProvider(String provider) { this.provider = provider; }
        public DeepSeek getDeepseek() { return deepseek; }
        public void setDeepseek(DeepSeek deepseek) { this.deepseek = deepseek; }
        public Anthropic getAnthropic() { return anthropic; }
        public void setAnthropic(Anthropic anthropic) { this.anthropic = anthropic; }
        public OpenAi getOpenai() { return openai; }
        public void setOpenai(OpenAi openai) { this.openai = openai; }
    }

    public static class DeepSeek {
        private String apiKey = "";
        private String model = "deepseek-chat";

        public String getApiKey() { return apiKey; }
        public void setApiKey(String apiKey) { this.apiKey = apiKey; }
        public String getModel() { return model; }
        public void setModel(String model) { this.model = model; }
    }

    public static class Anthropic {
        private String apiKey = "";
        private String model = "claude-sonnet-4-20250514";

        public String getApiKey() { return apiKey; }
        public void setApiKey(String apiKey) { this.apiKey = apiKey; }
        public String getModel() { return model; }
        public void setModel(String model) { this.model = model; }
    }

    public static class OpenAi {
        private String apiKey = "";
        private String model = "gpt-4o";

        public String getApiKey() { return apiKey; }
        public void setApiKey(String apiKey) { this.apiKey = apiKey; }
        public String getModel() { return model; }
        public void setModel(String model) { this.model = model; }
    }

    // ── Embedding ──

    public static class Embedding {
        private String mode = "auto";
        private Local local = new Local();
        private Api api = new Api();
        private Ollama ollama = new Ollama();

        public String getMode() { return mode; }
        public void setMode(String mode) { this.mode = mode; }
        public Local getLocal() { return local; }
        public void setLocal(Local local) { this.local = local; }
        public Api getApi() { return api; }
        public void setApi(Api api) { this.api = api; }
        public Ollama getOllama() { return ollama; }
        public void setOllama(Ollama ollama) { this.ollama = ollama; }

        public static class Local {
            private String model = "bge-small.onnx";
            private String modelPath = "./models/bge-small.onnx";

            public String getModel() { return model; }
            public void setModel(String model) { this.model = model; }
            public String getModelPath() { return modelPath; }
            public void setModelPath(String modelPath) { this.modelPath = modelPath; }
        }

        public static class Api {
            private String endpoint = "http://embedding-service:8080";
            private String apiKey = "";
            private String model = "text-embedding-3-small";

            public String getEndpoint() { return endpoint; }
            public void setEndpoint(String endpoint) { this.endpoint = endpoint; }
            public String getApiKey() { return apiKey; }
            public void setApiKey(String apiKey) { this.apiKey = apiKey; }
            public String getModel() { return model; }
            public void setModel(String model) { this.model = model; }
        }

        public static class Ollama {
            private String endpoint = "http://localhost:11434";
            private String model = "nomic-embed-text";

            public String getEndpoint() { return endpoint; }
            public void setEndpoint(String endpoint) { this.endpoint = endpoint; }
            public String getModel() { return model; }
            public void setModel(String model) { this.model = model; }
        }
    }

    // ── Memory ──

    public static class Memory {
        private String dbPath = "./data/context_os.db";
        private int maxTokens = 128000;

        public String getDbPath() { return dbPath; }
        public void setDbPath(String dbPath) { this.dbPath = dbPath; }
        public int getMaxTokens() { return maxTokens; }
        public void setMaxTokens(int maxTokens) { this.maxTokens = maxTokens; }
    }

    // ── Trace ──

    public static class Trace {
        private boolean enabled = true;
        private String storageDir = "./data/traces";

        public boolean isEnabled() { return enabled; }
        public void setEnabled(boolean enabled) { this.enabled = enabled; }
        public String getStorageDir() { return storageDir; }
        public void setStorageDir(String storageDir) { this.storageDir = storageDir; }
    }
}
