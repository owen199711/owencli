package com.owencli.contextos.optimizer;

import com.owencli.contextos.core.model.*;
import com.owencli.contextos.prompt.MemoryInjectionFormatter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Prompt Layout — structures the final context into a well-organized XML prompt.
 * <p>
 * Output format:
 * <pre>
 * System: You are an intelligent Context-OS Agent.
 *
 * &lt;memory&gt;
 * User Context:
 * - name: 李四
 * - occupation: backend engineer
 *
 * History:
 * - [long_term] task...
 * - [episodic] scene...
 *
 * Recent Conversation:
 * user: ...
 * assistant: ...
 *
 * Learned Patterns:
 * - [Consolidated Preference] ...
 *
 * Facts:
 * - [context | 0.95] user.name = 李四
 * - [context | 0.95] user.occupation = backend engineer
 * &lt;/memory&gt;
 * </pre>
 */
public class PromptLayout {

    private static final Logger log = LoggerFactory.getLogger(PromptLayout.class);

    private final MemoryInjectionFormatter injectionFormatter;

    public PromptLayout() {
        this.injectionFormatter = new MemoryInjectionFormatter(2000);
    }

    public PromptLayout(MemoryInjectionFormatter injectionFormatter) {
        this.injectionFormatter = injectionFormatter;
    }

    public PackagedContext layout(OptimizedContext optimized, LLMProvider provider) {
        var ctx = optimized.getContext();
        var packaged = new PackagedContext();
        var sections = new LinkedHashMap<String, String>();

        // ── 1. System identity ──
        String systemPart = buildIdentitySection(ctx.getIdentity());
        sections.put("system", systemPart);

        // ── 2. <memory> block ──
        var memoryBlock = new StringBuilder();
        memoryBlock.append("<memory>\n");

        // 2a. User Context (from fact memories — use InjectionFormatter for grouping)
        var factRecords = extractFactRecords(ctx.getMemory());
        if (!factRecords.isEmpty()) {
            String userContext = injectionFormatter.formatUserFacts(factRecords);
            memoryBlock.append("User Context:\n");
            // Clean up the <memory> tags from formatUserFacts output
            String cleanFacts = userContext
                    .replace("<memory>\n", "")
                    .replace("\n</memory>", "")
                    .trim();
            memoryBlock.append(cleanFacts).append("\n");
        }

        // 2b. History (non-fact, non-conversation memory items)
        var historyLines = new StringBuilder();
        if (ctx.getMemory() != null) {
            // Learned behaviors shown first
            for (var mem : ctx.getMemory()) {
                if (mem.getType() == MemoryType.LEARNED_BEHAVIOR) {
                    historyLines.append("- ").append(mem.getContent()).append("\n");
                }
            }
            // Then LTM + Episodic
            for (var mem : ctx.getMemory()) {
                if (mem.getType() != MemoryType.FACT && mem.getType() != MemoryType.CONVERSATION
                        && mem.getType() != MemoryType.LEARNED_BEHAVIOR) {
                    historyLines.append("- [").append(mem.getType().getValue()).append("] ")
                            .append(mem.getContent()).append("\n");
                }
            }
        }
        if (!historyLines.isEmpty()) {
            memoryBlock.append("\nHistory:\n").append(historyLines);
        }

        // 2c. Recent conversation
        if (ctx.getConversation() != null &&
                ctx.getConversation().getHistory() != null &&
                !ctx.getConversation().getHistory().isEmpty()) {
            memoryBlock.append("\nRecent Conversation:\n");
            var turns = ctx.getConversation().getHistory();
            int start = Math.max(0, turns.size() - 6);
            for (int i = start; i < turns.size(); i++) {
                var turn = turns.get(i);
                memoryBlock.append(turn.getRole()).append(": ")
                        .append(truncate(turn.getContent(), 300)).append("\n");
            }
        }

        // 2d. Full facts table (injection-formatted, confidence-sorted, token-aware)
        if (!factRecords.isEmpty()) {
            String formattedFacts = injectionFormatter.format(factRecords);
            if (!formattedFacts.isEmpty()) {
                memoryBlock.append("\n").append(formattedFacts).append("\n");
            }
        }

        memoryBlock.append("</memory>");
        sections.put("memory", memoryBlock.toString());

        // ── 3. Tool notice ──
        if (ctx.getTools() != null && !ctx.getTools().isEmpty()) {
            StringBuilder toolBlock = new StringBuilder("\nAvailable tools:\n");
            for (var t : ctx.getTools()) {
                toolBlock.append("- ").append(t.getName()).append("\n");
            }
            sections.put("tools", toolBlock.toString());
        }

        // ── Assemble ──
        var prompt = new StringBuilder();
        prompt.append(systemPart).append("\n\n");
        prompt.append(memoryBlock);
        if (sections.containsKey("tools")) {
            prompt.append("\n").append(sections.get("tools"));
        }

        packaged.setProvider(provider);
        packaged.setRawPrompt(prompt.toString().trim());
        packaged.setSections(sections);

        log.info("PromptLayout: {} sections, {} chars", sections.size(), packaged.getRawPrompt().length());
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

    /** Extract FactRecord instances from the unified context's memory items. */
    private java.util.List<com.owencli.contextos.core.model.FactRecord> extractFactRecords(
            java.util.List<MemoryItem> memoryItems) {
        return extractFactRecords(memoryItems, 0.0);
    }

    /**
     * Extract FactRecord instances filtered by minimum relevance score.
     * <p>
     * This is the L1 intent-level defense: facts with a relevance score below
     * the threshold are excluded from prompt injection, even if they were
     * retrieved. This prevents irrelevant personal data (e.g. user.name)
     * from being injected into unrelated task contexts (e.g. "写 K8s Deployment").
     *
     * @param memoryItems      the source memory items
     * @param minRelevanceScore minimum relevance threshold; facts below this are skipped
     */
    private java.util.List<com.owencli.contextos.core.model.FactRecord> extractFactRecords(
            java.util.List<MemoryItem> memoryItems, double minRelevanceScore) {
        if (memoryItems == null) return java.util.List.of();
        var records = new java.util.ArrayList<com.owencli.contextos.core.model.FactRecord>();
        for (var item : memoryItems) {
            if (item.getType() == MemoryType.FACT && item.getRelevanceScore() >= minRelevanceScore) {
                var meta = item.getMetadata();
                if (meta != null) {
                    var record = new com.owencli.contextos.core.model.FactRecord();
                    record.setType((String) meta.getOrDefault("fact_type", ""));
                    record.setCurrentValue((String) meta.getOrDefault("current_value", ""));
                    record.setConfidence(toDouble(meta.getOrDefault("confidence", 0.8)));
                    record.setSource((String) meta.getOrDefault("source", ""));
                    record.setStatus("ACTIVE");
                    if (!record.getType().isEmpty() && !record.getCurrentValue().isEmpty()) {
                        records.add(record);
                    }
                }
            }
        }
        return records;
    }

    private double toDouble(Object obj) {
        if (obj instanceof Number n) return n.doubleValue();
        try { return Double.parseDouble(obj.toString()); }
        catch (Exception e) { return 0.8; }
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) + "..." : (s != null ? s : "");
    }
}
