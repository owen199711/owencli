package com.owencli.contextos.optimizer;

import com.owencli.contextos.core.model.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.StringJoiner;

/**
 * Prompt Layout — structures the final context into a well-organized prompt.
 * Defines the layout: System prompt → Identity → Memory → Knowledge → Tools → Task → Output Schema.
 */
public class PromptLayout {

    private static final Logger log = LoggerFactory.getLogger(PromptLayout.class);

    public PackagedContext layout(OptimizedContext optimized, LLMProvider provider) {
        var ctx = optimized.getContext();
        var packaged = new PackagedContext();
        var sections = new LinkedHashMap<String, String>();
        var prompt = new StringBuilder();

        // 1. System / Identity
        String identitySection = buildIdentitySection(ctx.getIdentity());
        sections.put("identity", identitySection);
        prompt.append(identitySection).append("\n\n");

        // 2. Environment
        if (ctx.getEnvironment() != null) {
            String envSection = "Environment:\n" + ctx.getEnvironment().toString();
            sections.put("environment", envSection);
            prompt.append(envSection).append("\n\n");
        }

        // 3. Memory (conversation + memories)
        if (ctx.getMemory() != null && !ctx.getMemory().isEmpty()) {
            var memBuilder = new StringBuilder("Relevant Memory:\n");
            for (var mem : ctx.getMemory()) {
                String typeLabel = mem.getType() != null ? mem.getType().getValue() : "unknown";
                memBuilder.append("- [").append(typeLabel)
                        .append("] ").append(mem.getContent()).append("\n");
            }
            sections.put("memory", memBuilder.toString());
            prompt.append(memBuilder).append("\n");
        }

        // 4. Knowledge
        if (ctx.getKnowledge() != null && !ctx.getKnowledge().isEmpty()) {
            var knBuilder = new StringBuilder("Knowledge:\n");
            for (var kn : ctx.getKnowledge()) {
                knBuilder.append(kn.getContent()).append("\n");
            }
            sections.put("knowledge", knBuilder.toString());
            prompt.append(knBuilder).append("\n");
        }

        // 5. Conversation context
        if (ctx.getConversation() != null &&
                ctx.getConversation().getHistory() != null &&
                !ctx.getConversation().getHistory().isEmpty()) {
            var convBuilder = new StringBuilder("Conversation History:\n");
            for (var turn : ctx.getConversation().getHistory()) {
                convBuilder.append(turn.getRole()).append(": ").append(turn.getContent()).append("\n");
            }
            sections.put("conversation", convBuilder.toString());
            prompt.append(convBuilder).append("\n");
        }

        // 6. Tools
        if (ctx.getTools() != null && !ctx.getTools().isEmpty()) {
            var toolBuilder = new StringBuilder("Available Tools:\n");
            for (var tool : ctx.getTools()) {
                toolBuilder.append("- ").append(tool.getName());
                if (tool.getSchema() != null && !tool.getSchema().isEmpty()) {
                    toolBuilder.append(": ").append(tool.getSchema());
                }
                toolBuilder.append("\n");
            }
            sections.put("tools", toolBuilder.toString());
            prompt.append(toolBuilder).append("\n");
        }

        // 7. Token budget
        if (optimized.getTokenUsage() != null) {
            String budgetInfo = String.format("Token Budget: %d / %d tokens",
                    optimized.getTokenUsage().getUsed(), optimized.getTokenUsage().getTotal());
            sections.put("budget", budgetInfo);
        }

        packaged.setProvider(provider);
        packaged.setRawPrompt(prompt.toString().trim());
        packaged.setSections(sections);

        log.info("PromptLayout: {} sections, total {} chars", sections.size(), packaged.getRawPrompt().length());
        return packaged;
    }

    private String buildIdentitySection(UserProfile profile) {
        var sb = new StringBuilder("System: You are an intelligent Context-OS Agent.");
        if (profile != null) {
            if (profile.getUserId() != null) sb.append("\nUser ID: ").append(profile.getUserId());
            if (profile.getRole() != null) sb.append("\nRole: ").append(profile.getRole());
            if (profile.getSkillLevel() != null) sb.append("\nSkill Level: ").append(profile.getSkillLevel());
            if (profile.getLanguage() != null) sb.append("\nLanguage: ").append(profile.getLanguage());
        }
        return sb.toString();
    }
}
