package com.owencli.contextos.behavior;

import com.owencli.contextos.core.model.EpisodeInfo;
import com.owencli.contextos.memory.LearnedBehaviorMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Behavior Detector — detects stable behavior patterns across episodes.
 * <p>
 * Four triggers:
 * <ol>
 *   <li><b>Repeated Success</b> — same intent, same action pattern, >=3 times success</li>
 *   <li><b>User Preference</b> — user repeatedly asks for the same style/format</li>
 *   <li><b>Tool Usage Pattern</b> — user consistently prefers certain tools</li>
 *   <li><b>Agent Reflection Learning</b> — failure → fix → repeated success → procedure</li>
 * </ol>
 */
public class BehaviorDetector {

    private static final Logger log = LoggerFactory.getLogger(BehaviorDetector.class);

    private final BehaviorCandidatePool pool;
    private final LearnedBehaviorMemory learnedBehavior;

    public BehaviorDetector(BehaviorCandidatePool pool, LearnedBehaviorMemory learnedBehavior) {
        this.pool = pool;
        this.learnedBehavior = learnedBehavior;
        log.info("BehaviorDetector initialized");
    }

    /**
     * Analyze a completed episode and detect potential behaviors.
     */
    public void analyzeEpisode(EpisodeInfo episode) {
        if (episode == null) return;

        // Trigger 1: Repeated Success Pattern
        detectRepeatedSuccess(episode);

        // Trigger 2: User Preference (style, format, detail level)
        detectUserPreference(episode);

        // Trigger 3: Tool Usage Pattern (if tools are involved)
        detectToolPattern(episode);

        // Trigger 4: Agent Reflection Learning (failure → fix → success)
        detectReflectionLearning(episode);
    }

    /**
     * Trigger 1: Repeated Success
     * Same intent + same action + success >= 3 times → candidate procedure
     */
    private void detectRepeatedSuccess(EpisodeInfo episode) {
        if (!episode.isSuccess()) return;
        if (episode.getIntent() == null || episode.getIntent().isBlank()) return;

        String behaviorKey = "procedure:" + episode.getIntent();
        String description = "Procedure: " + episode.getAction();

        boolean ready = pool.observe(behaviorKey, "procedure", description, true);
        log.trace("Trigger 1: procedure candidate '{}' ready={}", behaviorKey, ready);
    }

    /**
     * Trigger 2: User Preference
     * User repeatedly asks for detailed/concise/specific style.
     */
    private void detectUserPreference(EpisodeInfo episode) {
        String input = episode.getUserInput();
        if (input == null || input.isBlank()) return;

        String lower = input.toLowerCase();

        // Detect preference for detailed responses
        if (lower.contains("详细") || lower.contains("具体") || lower.contains("详细一点")
                || lower.contains("越详细") || lower.contains("detail") || lower.contains("explain in detail")
                || lower.contains("in detail") || lower.contains("more specific")) {
            boolean ready = pool.observe("preference:detailed_response", "preference",
                    "User prefers detailed responses", episode.isSuccess());
            if (ready) log.info("Preference consolidated: detailed_response");
        }

        // Detect preference for concise responses
        if (lower.contains("简短") || lower.contains("简洁") || lower.contains("简略")
                || lower.contains("keep it short") || lower.contains("brief") || lower.contains("concise")
                || lower.contains("tl;dr") || lower.contains("summary")) {
            boolean ready = pool.observe("preference:concise_response", "preference",
                    "User prefers concise responses", episode.isSuccess());
            if (ready) log.info("Preference consolidated: concise_response");
        }

        // Detect preference for code examples
        if (lower.contains("example") || lower.contains("代码示例") || lower.contains("举例")
                || lower.contains("show me") || lower.contains("demonstrate")) {
            boolean ready = pool.observe("preference:code_examples", "preference",
                    "User prefers code examples", episode.isSuccess());
            if (ready) log.info("Preference consolidated: code_examples");
        }
    }

    /**
     * Trigger 3: Tool Usage Pattern
     * User/agent consistently prefers certain tools.
     */
    private void detectToolPattern(EpisodeInfo episode) {
        List<String> tools = episode.getToolsUsed();
        if (tools == null || tools.isEmpty()) return;

        for (String tool : tools) {
            String behaviorKey = "tool_pattern:" + tool;
            boolean ready = pool.observe(behaviorKey, "tool_pattern",
                    "Tool usage: " + tool, episode.isSuccess());
            if (ready) log.info("Tool pattern consolidated: {}", tool);
        }
    }

    /**
     * Trigger 4: Agent Reflection Learning
     * Task failure → root cause found → applied fix → repeated success → learned procedure.
     */
    private void detectReflectionLearning(EpisodeInfo episode) {
        if (!episode.isSuccess()) return;
        if (episode.getRootCause() == null || episode.getRootCause().isBlank()) return;

        // A successful episode that had a root cause means a previous failure was resolved
        String behaviorKey = "reflection_learn:" + episode.getRootCause();
        String desc = "Learned from " + episode.getRootCause() + " → " + episode.getAction();

        boolean ready = pool.observe(behaviorKey, "reflection_learning", desc, true);
        if (ready) {
            log.info("Reflection learning consolidated: {} → {}", episode.getRootCause(), episode.getAction());
        }
    }
}
