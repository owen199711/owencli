package com.owencli.contextos.packager.adapters;

import com.owencli.contextos.core.model.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * DeepSeek prompt adapter (OpenAI-compatible format).
 */
public class DeepSeekAdapter implements BasePromptAdapter {

    private static final Logger log = LoggerFactory.getLogger(DeepSeekAdapter.class);

    @Override
    public String getProvider() {
        return "deepseek";
    }

    @Override
    public PackagedContext pack(OptimizedContext context) {
        var ctx = context.getContext();
        var result = new PackagedContext();
        result.setProvider(LLMProvider.DEEPSEEK);

        var sections = result.getSections();
        var sb = new StringBuilder();

        sb.append("System: You are a helpful AI assistant with context-aware capabilities.\n\n");

        if (ctx.getIdentity() != null) {
            var id = ctx.getIdentity();
            var sec = String.format(
                    "[Identity]\nUser: %s\nRole: %s\nLanguage: %s\n\n",
                    id.getUserId(), id.getRole(), id.getLanguage());
            sections.put("identity", sec);
            sb.append(sec);
        }

        if (ctx.getConversation() != null && !ctx.getConversation().getHistory().isEmpty()) {
            var cb = new StringBuilder();
            cb.append("[Conversation History]\n");
            for (var turn : ctx.getConversation().getHistory()) {
                cb.append(turn.getRole()).append(": ").append(turn.getContent()).append("\n");
            }
            cb.append("\n");
            var sec = cb.toString();
            sections.put("conversation", sec);
            sb.append(sec);
        }

        if (ctx.getEnvironment() != null) {
            var env = ctx.getEnvironment();
            var sec = String.format("[Environment]\nOS: %s\nCWD: %s\n\n",
                    env.getOs(), env.getWorkingDirectory());
            sections.put("environment", sec);
            sb.append(sec);
        }

        if (!ctx.getMemory().isEmpty()) {
            var mb = new StringBuilder();
            mb.append("[Memory]\n");
            for (var mem : ctx.getMemory()) {
                mb.append("- ").append(mem.getContent()).append("\n");
            }
            mb.append("\n");
            var sec = mb.toString();
            sections.put("memory", sec);
            sb.append(sec);
        }

        if (!ctx.getKnowledge().isEmpty()) {
            var kb = new StringBuilder();
            kb.append("[Knowledge]\n");
            for (var kn : ctx.getKnowledge()) {
                kb.append("- [").append(kn.getSource()).append("] ").append(kn.getContent()).append("\n");
            }
            kb.append("\n");
            sections.put("knowledge", kb.toString());
        }

        result.setRawPrompt(sb.toString());
        log.info("DeepSeek prompt packed: {} chars", result.getRawPrompt().length());
        return result;
    }
}
