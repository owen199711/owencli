package com.owencli.contextos.llm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.owencli.contextos.core.base.BaseLLMClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.concurrent.CompletableFuture;

/**
 * Anthropic Claude API client.
 */
public class AnthropicClient implements BaseLLMClient {

    private static final Logger log = LoggerFactory.getLogger(AnthropicClient.class);
    private static final String DEFAULT_BASE_URL = "https://api.anthropic.com/v1";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final String apiKey;
    private final String model;
    private final String baseUrl;
    private final HttpClient httpClient;

    public AnthropicClient() {
        this(
                System.getenv("ANTHROPIC_API_KEY"),
                "claude-sonnet-4-20250514",
                DEFAULT_BASE_URL
        );
    }

    public AnthropicClient(String apiKey, String model, String baseUrl) {
        this.apiKey = apiKey != null && !apiKey.isEmpty() ? apiKey : System.getenv("ANTHROPIC_API_KEY");
        this.model = model != null ? model : "claude-sonnet-4-20250514";
        this.baseUrl = baseUrl != null ? baseUrl : DEFAULT_BASE_URL;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(30))
                .build();

        if (this.apiKey == null || this.apiKey.isEmpty()) {
            log.warn("ANTHROPIC_API_KEY not set");
        }
        log.info("AnthropicClient initialized: model={}", this.model);
    }

    @Override
    public CompletableFuture<Object> complete(String prompt, String system, int maxTokens,
                                              double temperature, String responseFormat) {
        return CompletableFuture.supplyAsync(() -> {
            try {
                var root = MAPPER.createObjectNode();
                root.put("model", model);
                root.put("max_tokens", maxTokens);
                root.put("temperature", temperature);

                if (system != null && !system.isEmpty()) {
                    root.put("system", system);
                }

                ArrayNode messages = MAPPER.createArrayNode();
                var msg = MAPPER.createObjectNode();
                msg.put("role", "user");
                msg.put("content", prompt);
                messages.add(msg);
                root.set("messages", messages);

                String requestBody = MAPPER.writeValueAsString(root);
                log.debug("Claude request: model={}, max_tokens={}", model, maxTokens);

                var request = HttpRequest.newBuilder()
                        .uri(URI.create(baseUrl + "/messages"))
                        .header("x-api-key", apiKey)
                        .header("anthropic-version", "2023-06-01")
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(requestBody))
                        .timeout(Duration.ofSeconds(120))
                        .build();

                HttpResponse<String> response = httpClient.send(request,
                        HttpResponse.BodyHandlers.ofString());

                if (response.statusCode() != 200) {
                    log.error("Claude API error: status={}, body={}",
                            response.statusCode(), response.body());
                    throw new RuntimeException("Claude API error: " + response.statusCode());
                }

                JsonNode json = MAPPER.readTree(response.body());
                String text = json.get("content").get(0).get("text").asText();

                log.debug("Claude response: stop_reason={}",
                        json.get("stop_reason").asText());

                if ("json".equals(responseFormat)) {
                    return MAPPER.readTree(text);
                }
                return text;

            } catch (Exception e) {
                log.error("Claude API error: {}", e.getMessage(), e);
                throw new RuntimeException("Claude API call failed", e);
            }
        });
    }
}
