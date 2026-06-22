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
 * API-based embedding service — calls a remote HTTP endpoint for embeddings.
 * <p>
 * Suitable for enterprise users who run a dedicated embedding service.
 * Compatible with OpenAI-compatible embedding APIs, Jina AI, etc.
 */
public class APIEmbeddingService implements EmbeddingService {

    private static final Logger log = LoggerFactory.getLogger(APIEmbeddingService.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final HttpClient client;
    private final String endpoint;
    private final String apiKey;
    private final String model;

    public APIEmbeddingService(String endpoint, String apiKey, String model) {
        this.client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
        this.endpoint = endpoint;
        this.apiKey = apiKey;
        this.model = model;
        log.info("APIEmbeddingService: endpoint={}, model={}", endpoint, model);
    }

    @Override
    public CompletableFuture<List<Double>> embed(String text) {
        if (text == null || text.isBlank()) {
            return CompletableFuture.completedFuture(null);
        }

        return CompletableFuture.supplyAsync(() -> {
            try {
                // Build request body (OpenAI-compatible format)
                var requestBody = new LinkedHashMap<String, Object>();
                requestBody.put("model", model);
                requestBody.put("input", text);

                var requestBuilder = HttpRequest.newBuilder()
                        .uri(URI.create(endpoint + (endpoint.endsWith("/") ? "" : "/") + "embeddings"))
                        .header("Content-Type", "application/json")
                        .timeout(Duration.ofSeconds(30));

                if (apiKey != null && !apiKey.isEmpty()) {
                    requestBuilder.header("Authorization", "Bearer " + apiKey);
                }

                var request = requestBuilder
                        .POST(HttpRequest.BodyPublishers.ofString(MAPPER.writeValueAsString(requestBody)))
                        .build();

                var response = client.send(request, HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() != 200) {
                    log.warn("API embedding failed: status={}, body={}", response.statusCode(),
                            truncate(response.body(), 200));
                    return new ArrayList<>();
                }

                return parseEmbeddingResponse(response.body());
            } catch (Exception e) {
                log.warn("API embedding request failed: {}", e.getMessage());
                return new ArrayList<>();
            }
        });
    }

    @SuppressWarnings("unchecked")
    private List<Double> parseEmbeddingResponse(String json) {
        try {
            var root = MAPPER.readTree(json);
            var data = root.get("data");
            if (data != null && data.isArray() && data.size() > 0) {
                var embedding = data.get(0).get("embedding");
                if (embedding != null && embedding.isArray()) {
                    var result = new ArrayList<Double>(embedding.size());
                    for (var elem : embedding) {
                        result.add(elem.asDouble());
                    }
                    return result;
                }
            }

            // Alternative: direct vector response format
            var vector = root.get("vector");
            if (vector != null && vector.isArray()) {
                var result = new ArrayList<Double>(vector.size());
                for (var elem : vector) {
                    result.add(elem.asDouble());
                }
                return result;
            }
        } catch (Exception e) {
            log.warn("Failed to parse embedding response: {}", e.getMessage());
        }
        return new ArrayList<>();
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }
}
