package com.owencli.contextos.packager.adapters;

import com.owencli.contextos.core.model.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class ClaudeAdapter implements BasePromptAdapter {
    private static final Logger log = LoggerFactory.getLogger(ClaudeAdapter.class);

    @Override public String getProvider() { return "claude"; }

    @Override
    public PackagedContext pack(OptimizedContext context) {
        var ctx = context.getContext();
        var packaged = new PackagedContext();
        packaged.setProvider(LLMProvider.CLAUDE);
        var sections = packaged.getSections();
        var sb = new StringBuilder();
        sb.append("<system>You are a helpful AI assistant with context-aware capabilities.</system>\n\n");

        if (ctx.getIdentity() != null) {
            var id = ctx.getIdentity();
            sections.put("identity", String.format("<identity><user_id>%s</user_id><role>%s</role><language>%s</language></identity>\n",
                    id.getUserId(), id.getRole(), id.getLanguage()));
        }
        if (ctx.getConversation() != null && !ctx.getConversation().getHistory().isEmpty()) {
            var cb = new StringBuilder("<conversation_history>\n");
            for (var t : ctx.getConversation().getHistory())
                cb.append("<turn role=\"").append(t.getRole()).append("\">").append(escapeXml(t.getContent())).append("</turn>\n");
            cb.append("</conversation_history>\n");
            sections.put("conversation", cb.toString());
            sb.append(cb);
        }
        if (ctx.getEnvironment() != null) {
            var env = ctx.getEnvironment();
            sections.put("environment", String.format("<environment><os>%s</os><working_directory>%s</working_directory></environment>\n",
                    env.getOs(), env.getWorkingDirectory()));
        }
        if (!ctx.getMemory().isEmpty()) {
            var mb = new StringBuilder("<memory>\n");
            for (var m : ctx.getMemory()) mb.append("<item>").append(escapeXml(m.getContent())).append("</item>\n");
            mb.append("</memory>\n");
            sections.put("memory", mb.toString());
            sb.append(mb);
        }
        packaged.setRawPrompt(sb.toString());
        log.info("Claude prompt packed: {} chars", packaged.getRawPrompt().length());
        return packaged;
    }

    private static String escapeXml(String s) {
        if (s == null) return "";
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }
}
