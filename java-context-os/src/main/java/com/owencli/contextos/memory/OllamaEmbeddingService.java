package com.owencli.contextos.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.CompletableFuture;

/**
 * Ollama-based embedding service — calls Ollama's local API for embeddings.
 * <p>
 * For users who already run Ollama locally. Compatible with any Ollama embedding model
 * (nomic-embed-text, llama3, mistral, etc.).
 * <p>
 * API: POST {@code http://localhost:11434/api/embeddings}
 * Body: {"model": "nomic-embed-text", "prompt": "text to embed"}
 */
public class OllamaEmbeddingService implements EmbeddingService {

    private static final Logger log = LoggerFactory.getLogger(OllamaEmbeddingService.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final HttpClient client;
    private final String endpoint;
    private final String model;

    public OllamaEmbeddingService(String endpoint, String model) {
        this.client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
        this.endpoint = endpoint;
        this.model = model;
        log.info("OllamaEmbeddingService: endpoint={}, model={}", endpoint, model);
    }

    @Override
    public CompletableFuture<List<Double>> embed(String text) {
        if (text == null || text.isBlank()) {
            return CompletableFuture.completedFuture(null);
        }

        return CompletableFuture.supplyAsync(() -> {
            try {
                var requestBody = new LinkedHashMap<String, Object>();
                requestBody.put("model", model);
                requestBody.put("prompt", text);

                String apiUrl = endpoint + (endpoint.endsWith("/") ? "" : "/")
                        + "api/embeddings";

                var request = HttpRequest.newBuilder()
                        .uri(URI.create(apiUrl))
                        .header("Content-Type", "application/json")
                        .timeout(Duration.ofSeconds(30))
                        .POST(HttpRequest.BodyPublishers.ofString(MAPPER.writeValueAsString(requestBody)))
                        .build();

                var response = client.send(request, HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() != 200) {
                    log.warn("Ollama embedding failed: status={}, body={}", response.statusCode(),
                            truncate(response.body(), 200));
                    return new ArrayList<>();
                }

                return parseEmbeddingResponse(response.body());
            } catch (Exception e) {
                log.warn("Ollama embedding request failed: {}", e.getMessage());
                return new ArrayList<>();
            }
        });
    }

    private List<Double> parseEmbeddingResponse(String json) {
        try {
            var root = MAPPER.readTree(json);
            var embedding = root.get("embedding");
            if (embedding != null && embedding.isArray()) {
                var result = new ArrayList<Double>(embedding.size());
                for (var elem : embedding) {
                    result.add(elem.asDouble());
                }
                return result;
            }
        } catch (Exception e) {
            log.warn("Failed to parse Ollama embedding response: {}", e.getMessage());
        }
        return new ArrayList<>();
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }
}
