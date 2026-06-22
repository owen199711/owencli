package com.owencli.contextos.memory;

import com.owencli.contextos.core.config.ContextOsProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Factory for creating EmbeddingService implementations based on configuration.
 * <p>
 * Supports modes:
 * <ul>
 *   <li><b>auto</b> — Try local ONNX first, fallback to BM25 keyword</li>
 *   <li><b>local</b> — Use built-in ONNX model (bge-small / gte-small)</li>
 *   <li><b>api</b> — Call a remote embedding service HTTP endpoint</li>
 *   <li><b>ollama</b> — Use local Ollama embedding API</li>
 *   <li><b>disable</b> — Use BM25/keyword-only retrieval</li>
 * </ul>
 */
public class EmbeddingServiceFactory {

    private static final Logger log = LoggerFactory.getLogger(EmbeddingServiceFactory.class);

    private final ContextOsProperties.Embedding config;

    public EmbeddingServiceFactory(ContextOsProperties.Embedding config) {
        this.config = config;
    }

    /**
     * Create the appropriate EmbeddingService based on configured mode.
     */
    public EmbeddingService create() {
        String mode = config.getMode() != null ? config.getMode().toLowerCase() : "auto";
        log.info("Creating EmbeddingService with mode: {}", mode);

        return switch (mode) {
            case "local" -> createLocal();
            case "api" -> createApi();
            case "ollama" -> createOllama();
            case "disable" -> new BM25EmbeddingService();
            case "auto" -> createAuto();
            default -> {
                log.warn("Unknown embedding mode '{}', falling back to auto", mode);
                yield createAuto();
            }
        };
    }

    private EmbeddingService createLocal() {
        String modelPath = config.getLocal().getModelPath();
        try {
            var onnxService = new ONNXEmbeddingService(modelPath);
            log.info("Local ONNX embedding service created: model={}, path={}",
                    config.getLocal().getModel(), modelPath);
            return onnxService;
        } catch (Throwable e) {
            log.warn("Failed to load ONNX model '{}', falling back to BM25: {}",
                    modelPath, e.getMessage());
            return new BM25EmbeddingService();
        }
    }

    private EmbeddingService createApi() {
        String endpoint = config.getApi().getEndpoint();
        String apiKey = config.getApi().getApiKey();
        String model = config.getApi().getModel();
        var apiService = new APIEmbeddingService(endpoint, apiKey, model);
        log.info("API embedding service created: endpoint={}, model={}", endpoint, model);
        return apiService;
    }

    private EmbeddingService createOllama() {
        String endpoint = config.getOllama().getEndpoint();
        String model = config.getOllama().getModel();
        var ollamaService = new OllamaEmbeddingService(endpoint, model);
        log.info("Ollama embedding service created: endpoint={}, model={}", endpoint, model);
        return ollamaService;
    }

    private EmbeddingService createAuto() {
        // Try ONNX first, fall back to BM25
        String modelPath = config.getLocal().getModelPath();
        try {
            var onnxService = new ONNXEmbeddingService(modelPath);
            log.info("Auto mode: ONNX model loaded successfully: {}", modelPath);
            return onnxService;
        } catch (Throwable e) {
            log.info("Auto mode: ONNX not available ({}), using BM25 fallback", e.getMessage());
            return new BM25EmbeddingService();
        }
    }
}
