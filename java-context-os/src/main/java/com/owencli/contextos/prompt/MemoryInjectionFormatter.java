package com.owencli.contextos.prompt;

import com.owencli.contextos.core.model.FactRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Memory Injection Formatter — formats memory data for system prompt injection.
 * <p>
 * Port of DeerFlow's {@code format_memory_for_injection()} with:
 * <ul>
 *   <li>Token-aware budget limiting</li>
 *   <li>Confidence-sorted facts (highest first)</li>
 *   <li>Sectioned output: User Context / History / Facts</li>
 *   <li>Correction facts include "(avoid: ...)" annotation</li>
 * </ul>
 * <p>
 * Output format:
 * <pre>
 * User Context:
 * - Work: ...
 * - Personal: ...
 * - Current Focus: ...
 *
 * History:
 * - Recent: ...
 * - Background: ...
 *
 * Facts:
 * - [context | 0.95] User is a backend architect at ByteDance
 * - [correction | 0.95] Agent should not record file upload events
 * </pre>
 */
public class MemoryInjectionFormatter {

    private static final Logger log = LoggerFactory.getLogger(MemoryInjectionFormatter.class);

    /** Approximate bytes per token for CJK-mixed text. */
    private static final double BYTES_PER_TOKEN = 4.0;

    private final int maxTokens;

    public MemoryInjectionFormatter() {
        this(2000);
    }

    public MemoryInjectionFormatter(int maxTokens) {
        this.maxTokens = maxTokens;
        log.info("MemoryInjectionFormatter initialized (maxTokens={})", maxTokens);
    }

    /**
     * Format fact memory data into an injection-ready string.
     *
     * @param facts List of active FactRecords.
     * @return Formatted string, truncated to maxTokens.
     */
    public String format(List<FactRecord> facts) {
        if (facts == null || facts.isEmpty()) return "";

        var sections = new ArrayList<String>();

        // ── User Context (facts grouped by type) ──
        var userContextLines = new ArrayList<String>();
        for (var f : facts) {
            if (f.isActive() && f.getType() != null) {
                String label = switch (f.getType()) {
                    case FactRecord.TYPE_OCCUPATION, FactRecord.TYPE_COMPANY -> "Work";
                    case FactRecord.TYPE_NAME, FactRecord.TYPE_LOCATION, FactRecord.TYPE_LANGUAGE -> "Personal";
                    case FactRecord.TYPE_GOAL, FactRecord.TYPE_PREFERENCE -> "Current Focus";
                    default -> null;
                };
                if (label != null) {
                    String line = label + ": " + typeToLabel(f.getType()) + " = " + f.getCurrentValue();
                    if (!userContextLines.contains(line)) {
                        userContextLines.add(line);
                    }
                }
            }
        }
        if (!userContextLines.isEmpty()) {
            sections.add("User Context:\n- " + String.join("\n- ", userContextLines));
        }

        // ── History (knowledge + behavior + skill facts) ──
        var historyLines = new ArrayList<String>();
        for (var f : facts) {
            if (f.isActive() && (
                    FactRecord.TYPE_KNOWLEDGE.equals(f.getType()) ||
                            FactRecord.TYPE_SKILL.equals(f.getType()) ||
                            FactRecord.TYPE_BEHAVIOR.equals(f.getType()))) {
                historyLines.add(f.getType().replace("user.", "") + ": " + f.getCurrentValue()
                        + " (confidence=" + String.format("%.2f", f.getConfidence()) + ")");
            }
        }
        if (!historyLines.isEmpty()) {
            sections.add("History:\n- " + String.join("\n- ", historyLines));
        }

        // ── Facts (sorted by confidence descending, truncated by token budget) ──
        var rankedFacts = facts.stream()
                .filter(FactRecord::isActive)
                .sorted(Comparator.comparingDouble(FactRecord::getConfidence).reversed())
                .collect(Collectors.toList());

        // Compute base token count
        String baseText = String.join("\n\n", sections);
        int baseTokens = estimateTokens(baseText);
        int runningTokens = baseTokens;

        var factLines = new ArrayList<String>();
        for (var f : rankedFacts) {
            String category = mapTypeToCategory(f.getType());
            String line = "- [" + category + " | " + String.format("%.2f", f.getConfidence()) + "] "
                    + f.getType() + " = " + f.getCurrentValue();
            if (FactRecord.TYPE_CORRECTION.equals(f.getType()) && f.getSourceError() != null && !f.getSourceError().isEmpty()) {
                line += " (avoid: " + f.getSourceError() + ")";
            }

            int lineTokens = estimateTokens(line + "\n");
            if (runningTokens + lineTokens <= maxTokens) {
                factLines.add(line);
                runningTokens += lineTokens;
            } else {
                break;
            }
        }

        if (!factLines.isEmpty()) {
            sections.add("Facts:\n" + String.join("\n", factLines));
        }

        String result = String.join("\n\n", sections);

        // Final token check
        if (estimateTokens(result) > maxTokens) {
            double ratio = (double) maxTokens / estimateTokens(result);
            int targetChars = (int) (result.length() * ratio * 0.95);
            result = result.substring(0, Math.min(targetChars, result.length())) + "\n...";
        }

        log.debug("Injection formatted: {} chars, ~{} tokens", result.length(), estimateTokens(result));
        return result;
    }

    /**
     * Format user facts specifically for injection into system prompt.
     * Groups by category for better readability.
     */
    public String formatUserFacts(List<FactRecord> facts) {
        if (facts == null || facts.isEmpty()) return "";

        var sb = new StringBuilder();
        sb.append("<memory>\n");

        // Active user facts (sorted by type for grouping)
        var active = facts.stream()
                .filter(FactRecord::isActive)
                .sorted(Comparator.comparing(FactRecord::getType))
                .collect(Collectors.toList());

        for (var f : active) {
            String typeLabel = f.getType().replace("user.", "");
            sb.append("- [").append(typeLabel).append(" | ")
                    .append(String.format("%.2f", f.getConfidence()))
                    .append("] ").append(f.getCurrentValue());
            if (f.getSourceError() != null && !f.getSourceError().isEmpty()) {
                sb.append(" (avoid: ").append(f.getSourceError()).append(")");
            }
            sb.append("\n");
        }

        sb.append("</memory>");
        return sb.toString();
    }

    private String typeToLabel(String type) {
        if (type == null) return "";
        return switch (type) {
            case FactRecord.TYPE_NAME -> "name";
            case FactRecord.TYPE_OCCUPATION -> "occupation";
            case FactRecord.TYPE_COMPANY -> "company";
            case FactRecord.TYPE_LOCATION -> "location";
            case FactRecord.TYPE_LANGUAGE -> "language";
            case FactRecord.TYPE_PREFERENCE -> "preference";
            case FactRecord.TYPE_GOAL -> "goal";
            case FactRecord.TYPE_SKILL -> "skill";
            case FactRecord.TYPE_KNOWLEDGE -> "knowledge";
            case FactRecord.TYPE_BEHAVIOR -> "behavior";
            default -> type.replace("user.", "");
        };
    }

    private String mapTypeToCategory(String type) {
        if (type == null) return "context";
        return switch (type) {
            case FactRecord.TYPE_PREFERENCE -> "preference";
            case FactRecord.TYPE_KNOWLEDGE, FactRecord.TYPE_SKILL -> "knowledge";
            case FactRecord.TYPE_NAME, FactRecord.TYPE_OCCUPATION, FactRecord.TYPE_COMPANY,
                    FactRecord.TYPE_LOCATION, FactRecord.TYPE_LANGUAGE -> "context";
            case FactRecord.TYPE_BEHAVIOR -> "behavior";
            case FactRecord.TYPE_GOAL -> "goal";
            case FactRecord.TYPE_CORRECTION -> "correction";
            default -> "context";
        };
    }

    /** Estimate token count (simple char/4 approximation). */
    private int estimateTokens(String text) {
        if (text == null || text.isEmpty()) return 0;
        return (int) Math.ceil(text.length() / BYTES_PER_TOKEN);
    }
}
