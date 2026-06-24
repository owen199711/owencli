package com.owencli.contextos.prompt;

import com.owencli.contextos.memory.FactMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Memory Summarization Prompt — LLM-driven structured memory update.
 * <p>
 * Port of DeerFlow's {@code MEMORY_UPDATE_PROMPT}.
 * Sends the current memory state + new conversation to the LLM,
 * which returns a structured JSON update.
 * <p>
 * This is used for high-importance content that needs semantic summarization,
 * not just keyword-based extraction.
 */
public class MemorySummarizationPrompt {

    private static final Logger log = LoggerFactory.getLogger(MemorySummarizationPrompt.class);

    private final FactMemory factMemory;

    public MemorySummarizationPrompt(FactMemory factMemory) {
        this.factMemory = factMemory;
        log.info("MemorySummarizationPrompt initialized");
    }

    /**
     * Build the full MEMORY_UPDATE_PROMPT with current memory + new conversation.
     */
    public CompletableFuture<String> buildPrompt(String userInput, String assistantResponse) {
        return factMemory.getFactsSummary().thenApply(currentMemory -> {
            String conversation = "User: " + userInput + "\n\nAssistant: " +
                    (assistantResponse != null ? assistantResponse : "");

            return String.format("""
                    You are a memory management system. Your task is to analyze a conversation and update the user's memory profile.
                    
                    Current Memory State:
                    <current_memory>
                    %s
                    </current_memory>
                    
                    New Conversation to Process:
                    <conversation>
                    %s
                    </conversation>
                    
                    Instructions:
                    1. Analyze the conversation for important information about the user
                    2. Extract relevant facts, preferences, and context with specific details
                    3. Update the memory sections as needed
                    
                    Before extracting facts, perform a structured reflection:
                    1. Error/Retry Detection: Did the agent encounter errors or produce incorrect results?
                       If yes, record the root cause as a correction fact with confidence >= 0.95.
                    2. User Correction Detection: Did the user correct the agent?
                       If yes, record the correct interpretation with category "correction".
                    3. Project Constraint Discovery: Were any project constraints discovered?
                    
                    Categories:
                    - preference: Tools, styles, approaches user prefers/dislikes
                    - knowledge: Specific expertise, technologies mastered
                    - context: Background facts (job title, projects, locations)
                    - behavior: Working patterns, communication habits
                    - goal: Stated objectives, learning targets
                    - correction: Agent mistakes or user corrections
                    
                    Confidence levels:
                    - 0.9-1.0: Explicitly stated facts
                    - 0.7-0.8: Strongly implied from discussions
                    - 0.5-0.6: Inferred patterns (use sparingly)
                    
                    Output Format (ONLY JSON, no explanation):
                    {
                      "newFacts": [
                        {"content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.95}
                      ],
                      "factsToRemove": [],
                      "summary": "Optional 1-sentence summary of what changed"
                    }
                    
                    Important Rules:
                    - Only extract clearly stated or strongly implied facts
                    - Use category "correction" for agent mistakes, confidence >= 0.95
                    - Include "sourceError" only for correction facts with explicit mistakes
                    - Remove facts contradicted by new information
                    - Return ONLY valid JSON, no markdown
                    """,
                    currentMemory.isEmpty() ? "(no existing memory)" : currentMemory,
                    conversation
            );
        });
    }

    /**
     * Parse the LLM response to extract structured fact candidates.
     * Returns a list of candidate fact descriptors.
     */
    public List<CandidateFactDescriptor> parseResponse(String llmResponse) {
        if (llmResponse == null || llmResponse.isBlank()) return List.of();

        try {
            var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
            var root = mapper.readTree(llmResponse);

            var results = new java.util.ArrayList<CandidateFactDescriptor>();

            var newFacts = root.get("newFacts");
            if (newFacts != null && newFacts.isArray()) {
                for (var fact : newFacts) {
                    String content = fact.has("content") ? fact.get("content").asText() : "";
                    String category = fact.has("category") ? fact.get("category").asText() : "context";
                    double confidence = fact.has("confidence") ? fact.get("confidence").asDouble() : 0.7;
                    String sourceError = fact.has("sourceError") ? fact.get("sourceError").asText() : "";

                    if (!content.isEmpty()) {
                        // Map category to fact type
                        String factType = switch (category) {
                            case "preference" -> "user.preference";
                            case "knowledge" -> "user.knowledge";
                            case "context" -> "user.context";
                            case "behavior" -> "user.behavior";
                            case "goal" -> "user.goal";
                            case "correction" -> "user.correction";
                            default -> "user.context";
                        };

                        results.add(new CandidateFactDescriptor(factType, content, confidence, sourceError, category));
                    }
                }
            }

            // Process factsToRemove
            var toRemove = root.get("factsToRemove");
            if (toRemove != null && toRemove.isArray()) {
                for (var id : toRemove) {
                    log.debug("LLM suggested removing fact: {}", id.asText());
                }
            }

            return results;
        } catch (Exception e) {
            log.warn("Failed to parse LLM memory update response: {}", e.getMessage());
            return List.of();
        }
    }

    /**
     * Parse the "summary" field from the LLM response.
     */
    public String parseSummary(String llmResponse) {
        try {
            var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
            var root = mapper.readTree(llmResponse);
            return root.has("summary") ? root.get("summary").asText() : "";
        } catch (Exception e) {
            return "";
        }
    }

    public record CandidateFactDescriptor(String type, String content, double confidence,
                                          String sourceError, String category) {}
}
