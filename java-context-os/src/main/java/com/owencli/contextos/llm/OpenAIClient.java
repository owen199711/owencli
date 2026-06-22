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

public class OpenAIClient implements BaseLLMClient {
    private static final Logger log = LoggerFactory.getLogger(OpenAIClient.class);
    private static final String DEFAULT_BASE_URL = "https://api.openai.com/v1";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final String apiKey;
    private final String model;
    private final String baseUrl;
    private final HttpClient httpClient;

    public OpenAIClient() { this(System.getenv("OPENAI_API_KEY"), "gpt-4o", DEFAULT_BASE_URL); }

    public OpenAIClient(String apiKey, String model, String baseUrl) {
        this.apiKey = (apiKey != null && !apiKey.isEmpty()) ? apiKey : System.getenv("OPENAI_API_KEY");
        this.model = model != null ? model : "gpt-4o";
        this.baseUrl = baseUrl != null ? baseUrl : DEFAULT_BASE_URL;
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(30)).build();
        if (this.apiKey == null || this.apiKey.isEmpty()) log.warn("OPENAI_API_KEY not set");
        log.info("OpenAIClient initialized: model={}", this.model);
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
                ArrayNode messages = MAPPER.createArrayNode();
                if (system != null && !system.isEmpty()) {
                    messages.add(MAPPER.createObjectNode().put("role", "system").put("content", system));
                }
                messages.add(MAPPER.createObjectNode().put("role", "user").put("content", prompt));
                root.set("messages", messages);
                if ("json".equals(responseFormat)) {
                    root.set("response_format", MAPPER.createObjectNode().put("type", "json_object"));
                }
                var request = HttpRequest.newBuilder()
                        .uri(URI.create(baseUrl + "/chat/completions"))
                        .header("Authorization", "Bearer " + apiKey)
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(MAPPER.writeValueAsString(root)))
                        .timeout(Duration.ofSeconds(120)).build();
                HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
                if (response.statusCode() != 200) throw new RuntimeException("OpenAI error: " + response.statusCode());
                String text = MAPPER.readTree(response.body()).get("choices").get(0).get("message").get("content").asText();
                return "json".equals(responseFormat) ? MAPPER.readTree(text) : text;
            } catch (Exception e) {
                log.error("OpenAI API error: {}", e.getMessage(), e);
                throw new RuntimeException("OpenAI API call failed", e);
            }
        });
    }
}
