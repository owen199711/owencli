package com.owencli.contextos.policy;

import com.owencli.contextos.core.model.TaskSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * Context Policy — defines policies for what context to retrieve based on
 * user, task type, token budget, privacy requirements, importance, and TTL.
 * <p>
 * Without policy, ALL memory would be retrieved for every query.
 * With policy, retrieval is scoped and efficient.
 */
public class ContextPolicy {

    private static final Logger log = LoggerFactory.getLogger(ContextPolicy.class);

    private final Map<String, PolicyRule> rules = new LinkedHashMap<>();

    public ContextPolicy() {
        // Default rules
        registerRule(new PolicyRule("simple_chat",
                Set.of("qa", "chat"),
                Set.of("skip_knowledge", "skip_tools"),
                0, 2000, 0.3, 7));

        registerRule(new PolicyRule("debug_session",
                Set.of("debugging"),
                Set.of("include_episodes", "include_reflections", "prioritize_recent"),
                5, 8000, 0.6, 1));

        registerRule(new PolicyRule("coding_task",
                Set.of("coding", "workflow"),
                Set.of("include_tools", "include_procedures", "include_knowledge"),
                3, 12000, 0.7, 3));

        registerRule(new PolicyRule("planning_session",
                Set.of("planning"),
                Set.of("include_all", "comprehensive"),
                10, 16000, 0.8, 30));

        registerRule(new PolicyRule("default",
                Set.of("default"),
                Set.of("balanced"),
                0, 4000, 0.5, 14));
    }

    public void registerRule(PolicyRule rule) {
        rules.put(rule.name(), rule);
        log.info("Policy rule registered: {} (intents={})", rule.name(), rule.intents());
    }

    public RetrievalDirective evaluate(TaskSpec task) {
        // Find matching rule
        PolicyRule matched = rules.get("default");
        for (var rule : rules.values()) {
            if (rule.intents().contains(task.getIntent().getValue())) {
                matched = rule;
                break;
            }
        }

        var directive = new RetrievalDirective();
        directive.setMatchedRule(matched.name());

        // Apply flags
        var flags = matched.flags();
        directive.setSkipKnowledge(flags.contains("skip_knowledge"));
        directive.setSkipTools(flags.contains("skip_tools"));
        directive.setIncludeEpisodes(flags.contains("include_episodes"));
        directive.setIncludeReflections(flags.contains("include_reflections"));
        directive.setPrioritizeRecent(flags.contains("prioritize_recent"));
        directive.setIncludeAll(flags.contains("include_all"));

        // Apply quantitative limits
        directive.setMinRelevanceScore(matched.minRelevanceScore());
        directive.setMaxTokenBudget(matched.maxTokenBudget());
        directive.setMaxAgeDays(matched.maxAgeDays());
        directive.setContextWindowSize(matched.contextWindowSize());

        log.info("ContextPolicy: rule={}, flags={}, minScore={}, maxTokens={}, maxAge={}d",
                matched.name(), flags, matched.minRelevanceScore(), matched.maxTokenBudget(), matched.maxAgeDays());
        return directive;
    }

    public record PolicyRule(String name, Set<String> intents, Set<String> flags,
                              int contextWindowSize, int maxTokenBudget,
                              double minRelevanceScore, int maxAgeDays) {}

    public static class RetrievalDirective {
        private String matchedRule = "default";
        private boolean skipKnowledge = false;
        private boolean skipTools = false;
        private boolean includeEpisodes = false;
        private boolean includeReflections = false;
        private boolean prioritizeRecent = false;
        private boolean includeAll = false;
        private double minRelevanceScore = 0.3;
        private int maxTokenBudget = 4000;
        private int maxAgeDays = 14;
        private int contextWindowSize = 0;

        public String getMatchedRule() { return matchedRule; }
        public void setMatchedRule(String v) { this.matchedRule = v; }
        public boolean isSkipKnowledge() { return skipKnowledge; }
        public void setSkipKnowledge(boolean v) { this.skipKnowledge = v; }
        public boolean isSkipTools() { return skipTools; }
        public void setSkipTools(boolean v) { this.skipTools = v; }
        public boolean isIncludeEpisodes() { return includeEpisodes; }
        public void setIncludeEpisodes(boolean v) { this.includeEpisodes = v; }
        public boolean isIncludeReflections() { return includeReflections; }
        public void setIncludeReflections(boolean v) { this.includeReflections = v; }
        public boolean isPrioritizeRecent() { return prioritizeRecent; }
        public void setPrioritizeRecent(boolean v) { this.prioritizeRecent = v; }
        public boolean isIncludeAll() { return includeAll; }
        public void setIncludeAll(boolean v) { this.includeAll = v; }
        public double getMinRelevanceScore() { return minRelevanceScore; }
        public void setMinRelevanceScore(double v) { this.minRelevanceScore = v; }
        public int getMaxTokenBudget() { return maxTokenBudget; }
        public void setMaxTokenBudget(int v) { this.maxTokenBudget = v; }
        public int getMaxAgeDays() { return maxAgeDays; }
        public void setMaxAgeDays(int v) { this.maxAgeDays = v; }
        public int getContextWindowSize() { return contextWindowSize; }
        public void setContextWindowSize(int v) { this.contextWindowSize = v; }
    }
}
