package main.java.com.owencli.contextos.core.config.model;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * AppConfig — 独立于 Spring 的配置模型。
 * <p>
 * 从 config.yaml 解析，支持 ${VAR} 环境变量替换。
 * 参考 DeerFlow AppConfig + ExtensionsConfig 设计。
 */
public class AppConfig {

    private long loadedAt;        // 加载时间戳
    private PipelineConfig pipeline = new PipelineConfig();
    private LlmConfig llm = new LlmConfig();
    private EmbeddingConfig embedding = new EmbeddingConfig();
    private MemoryConfig memory = new MemoryConfig();
    private StoreConfig store = new StoreConfig();
    private TraceConfig trace = new TraceConfig();

    public long getLoadedAt() { return loadedAt; }
    public void setLoadedAt(long loadedAt) { this.loadedAt = loadedAt; }
    public PipelineConfig getPipeline() { return pipeline; }
    public void setPipeline(PipelineConfig pipeline) { this.pipeline = pipeline; }
    public LlmConfig getLlm() { return llm; }
    public void setLlm(LlmConfig llm) { this.llm = llm; }
    public EmbeddingConfig getEmbedding() { return embedding; }
    public void setEmbedding(EmbeddingConfig embedding) { this.embedding = embedding; }
    public MemoryConfig getMemory() { return memory; }
    public void setMemory(MemoryConfig memory) { this.memory = memory; }
    public StoreConfig getStore() { return store; }
    public void setStore(StoreConfig store) { this.store = store; }
    public TraceConfig getTrace() { return trace; }
    public void setTrace(TraceConfig trace) { this.trace = trace; }

    // ── Pipeline ──
    public static class PipelineConfig {
        private List<MiddlewareDef> middlewares = new ArrayList<>();

        public List<MiddlewareDef> getMiddlewares() { return middlewares; }
        public void setMiddlewares(List<MiddlewareDef> middlewares) { this.middlewares = middlewares; }

        public static class MiddlewareDef {
            private String name;
            private boolean enabled = true;
            private int order;

            public String getName() { return name; }
            public void setName(String name) { this.name = name; }
            public boolean isEnabled() { return enabled; }
            public void setEnabled(boolean enabled) { this.enabled = enabled; }
            public int getOrder() { return order; }
            public void setOrder(int order) { this.order = order; }
        }
    }

    // ── LLM ──
    public static class LlmConfig {
        private String provider = "deepseek";
        private String apiKey = "";
        private String model = "deepseek-chat";
        private int maxTokens = 4096;

        public String getProvider() { return provider; }
        public void setProvider(String provider) { this.provider = provider; }
        public String getApiKey() { return apiKey; }
        public void setApiKey(String apiKey) { this.apiKey = apiKey; }
        public String getModel() { return model; }
        public void setModel(String model) { this.model = model; }
        public int getMaxTokens() { return maxTokens; }
        public void setMaxTokens(int maxTokens) { this.maxTokens = maxTokens; }
    }

    // ── Embedding ──
    public static class EmbeddingConfig {
        private String mode = "auto";
        private String apiEndpoint = "http://embedding-service:8080";
        private String apiKey = "";
        private String apiModel = "text-embedding-3-small";
        private String localModel = "bge-small.onnx";
        private String localModelPath = "./models/bge-small.onnx";
        private String ollamaEndpoint = "http://localhost:11434";
        private String ollamaModel = "nomic-embed-text";

        public String getMode() { return mode; }
        public void setMode(String mode) { this.mode = mode; }
        public String getApiEndpoint() { return apiEndpoint; }
        public void setApiEndpoint(String apiEndpoint) { this.apiEndpoint = apiEndpoint; }
        public String getApiKey() { return apiKey; }
        public void setApiKey(String apiKey) { this.apiKey = apiKey; }
        public String getApiModel() { return apiModel; }
        public void setApiModel(String apiModel) { this.apiModel = apiModel; }
        public String getLocalModel() { return localModel; }
        public void setLocalModel(String localModel) { this.localModel = localModel; }
        public String getLocalModelPath() { return localModelPath; }
        public void setLocalModelPath(String localModelPath) { this.localModelPath = localModelPath; }
        public String getOllamaEndpoint() { return ollamaEndpoint; }
        public void setOllamaEndpoint(String ollamaEndpoint) { this.ollamaEndpoint = ollamaEndpoint; }
        public String getOllamaModel() { return ollamaModel; }
        public void setOllamaModel(String ollamaModel) { this.ollamaModel = ollamaModel; }
    }

    // ── Memory ──
    public static class MemoryConfig {
        private WorkingMemoryConfig workingMemory = new WorkingMemoryConfig();
        private ShortTermConfig shortTerm = new ShortTermConfig();
        private LongTermConfig longTerm = new LongTermConfig();

        public WorkingMemoryConfig getWorkingMemory() { return workingMemory; }
        public void setWorkingMemory(WorkingMemoryConfig wm) { this.workingMemory = wm; }
        public ShortTermConfig getShortTerm() { return shortTerm; }
        public void setShortTerm(ShortTermConfig st) { this.shortTerm = st; }
        public LongTermConfig getLongTerm() { return longTerm; }
        public void setLongTerm(LongTermConfig lt) { this.longTerm = lt; }

        public static class WorkingMemoryConfig { private int maxTokens = 32000; public int getMaxTokens() { return maxTokens; } public void setMaxTokens(int v) { this.maxTokens = v; } }
        public static class ShortTermConfig { private int ttlHours = 24; public int getTtlHours() { return ttlHours; } public void setTtlHours(int v) { this.ttlHours = v; } }
        public static class LongTermConfig { private int maxItems = 1000; private int consolidationIntervalMin = 60; public int getMaxItems() { return maxItems; } public void setMaxItems(int v) { this.maxItems = v; } public int getConsolidationIntervalMin() { return consolidationIntervalMin; } public void setConsolidationIntervalMin(int v) { this.consolidationIntervalMin = v; } }
    }

    // ── Store ──
    public static class StoreConfig {
        private String provider = "sqlite";
        private String dbPath = "./data/context_os.db";
        private PostgresqlConfig postgresql = new PostgresqlConfig();

        public String getProvider() { return provider; }
        public void setProvider(String provider) { this.provider = provider; }
        public String getDbPath() { return dbPath; }
        public void setDbPath(String dbPath) { this.dbPath = dbPath; }
        public PostgresqlConfig getPostgresql() { return postgresql; }
        public void setPostgresql(PostgresqlConfig pg) { this.postgresql = pg; }

        public static class PostgresqlConfig {
            private String url = "jdbc:postgresql://localhost:5432/context_os";
            private String user = "app";
            private String password = "secret";

            public String getUrl() { return url; }
            public void setUrl(String url) { this.url = url; }
            public String getUser() { return user; }
            public void setUser(String user) { this.user = user; }
            public String getPassword() { return password; }
            public void setPassword(String password) { this.password = password; }
        }
    }

    // ── Trace ──
    public static class TraceConfig {
        private boolean enabled = true;
        private String storageDir = "./data/traces";

        public boolean isEnabled() { return enabled; }
        public void setEnabled(boolean enabled) { this.enabled = enabled; }
        public String getStorageDir() { return storageDir; }
        public void setStorageDir(String storageDir) { this.storageDir = storageDir; }
    }
}
