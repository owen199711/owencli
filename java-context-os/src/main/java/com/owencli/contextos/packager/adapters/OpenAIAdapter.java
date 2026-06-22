package com.owencli.contextos.packager.adapters;

import com.owencli.contextos.core.model.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * OpenAI JSON prompt adapter.
 */
public class OpenAIAdapter implements BasePromptAdapter {

    private static final Logger log = LoggerFactory.getLogger(OpenAIAdapter.class);

    @Override
    public String getProvider() {
        return "openai";
    }

    @Override
    public PackagedContext pack(OptimizedContext context) {
        var ctx = context.getContext();
        var packaged = new PackagedContext();
        packaged.setProvider(LLMProvider.OPENAI);

        var sections = packaged.getSections();
        var sb = new StringBuilder();

        sb.append("System: You are a helpful AI assistant with context-aware capabilities.\n\n");

        if (ctx.getIdentity() != null) {
            var id = ctx.getIdentity();
            var identitySection = String.format(
                    "[Identity]\nUser: %s\nRole: %s\nLanguage: %s\n\n",
                    id.getUserId(), id.getRole(), id.getLanguage());
            sections.put("identity", identitySection);
            sb.append(identitySection);
        }

        if (ctx.getConversation() != null && !ctx.getConversation().getHistory().isEmpty()) {
            var convBuilder = new StringBuilder();
            convBuilder.append("[Conversation History]\n");
            for (var turn : ctx.getConversation().getHistory()) {
                convBuilder.append(turn.getRole()).append(": ").append(turn.getContent()).append("\n");
            }
            convBuilder.append("\n");
            var convSection = convBuilder.toString();
            sections.put("conversation", convSection);
            sb.append(convSection);
        }

        if (ctx.getEnvironment() != null) {
            var env = ctx.getEnvironment();
            var envSection = String.format("[Environment]\nOS: %s\nCWD: %s\n\n",
                    env.getOs(), env.getWorkingDirectory());
            sections.put("environment", envSection);
            sb.append(envSection);
        }

        if (!ctx.getMemory().isEmpty()) {
            var memBuilder = new StringBuilder();
            memBuilder.append("[Memory]\n");
            for (var mem : ctx.getMemory()) {
                memBuilder.append("- ").append(mem.getContent()).append("\n");
            }
            memBuilder.append("\n");
            var memSection = memBuilder.toString();
            sections.put("memory", memSection);
            sb.append(memSection);
        }

        if (!ctx.getKnowledge().isEmpty()) {
            var knBuilder = new StringBuilder();
            knBuilder.append("[Knowledge]\n");
            for (var kn : ctx.getKnowledge()) {
                knBuilder.append("- [").append(kn.getSource()).append("] ").append(kn.getContent()).append("\n");
            }
            knBuilder.append("\n");
            sections.put("knowledge", knBuilder.toString());
        }

        packaged.setRawPrompt(sb.toString());
        log.info("OpenAI prompt packed: {} chars, {} sections",
                packaged.getRawPrompt().length(), sections.size());
        return packaged;
    }
}
