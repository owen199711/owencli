package com.owencli.contextos.builder;

import com.owencli.contextos.core.model.IntentType;
import com.owencli.contextos.core.model.TaskSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * Retrieval Planner — decides what sources to query and how many items per source,
 * based on task intent and domain.
 * <p>
 * Different tasks need different retrieval strategies:
 * <ul>
 *   <li>Coding → Tool + Knowledge heavy</li>
 *   <li>Chat → Conversation + Memory heavy</li>
 *   <li>Debugging → Episode + Reflection heavy</li>
 * </ul>
 */
public class RetrievalPlanner {

    private static final Logger log = LoggerFactory.getLogger(RetrievalPlanner.class);

    public RetrievalPlan plan(TaskSpec task) {
        IntentType intent = task.getIntent();
        String domain = task.getDomain();
        var plan = new RetrievalPlan();

        switch (intent) {
            case CODING -> {
                plan.setMemoryTopK(3);
                plan.setConversationTopK(5);
                plan.setEpisodeTopK(2);
                plan.setKnowledgeTopK(8);
                plan.setToolTopK(10);
                plan.setReflectionTopK(2);
                plan.setReason("Coding tasks need more tool and knowledge context");
            }
            case DEBUGGING -> {
                plan.setMemoryTopK(5);
                plan.setConversationTopK(10);
                plan.setEpisodeTopK(8);
                plan.setKnowledgeTopK(5);
                plan.setToolTopK(5);
                plan.setReflectionTopK(5);
                plan.setReason("Debugging tasks need more episode and reflection context");
            }
            case QA, SEARCH -> {
                plan.setMemoryTopK(8);
                plan.setConversationTopK(3);
                plan.setEpisodeTopK(2);
                plan.setKnowledgeTopK(10);
                plan.setToolTopK(1);
                plan.setReflectionTopK(1);
                plan.setReason("QA/Search tasks need more memory and knowledge context");
            }
            case PLANNING -> {
                plan.setMemoryTopK(10);
                plan.setConversationTopK(5);
                plan.setEpisodeTopK(5);
                plan.setKnowledgeTopK(8);
                plan.setToolTopK(3);
                plan.setReflectionTopK(3);
                plan.setReason("Planning tasks need comprehensive context from all sources");
            }
            case WORKFLOW, AGENT -> {
                plan.setMemoryTopK(5);
                plan.setConversationTopK(8);
                plan.setEpisodeTopK(5);
                plan.setKnowledgeTopK(5);
                plan.setToolTopK(8);
                plan.setReflectionTopK(3);
                plan.setReason("Workflow/Agent tasks need more tool and conversation context");
            }
            default -> {
                plan.setMemoryTopK(5);
                plan.setConversationTopK(5);
                plan.setEpisodeTopK(3);
                plan.setKnowledgeTopK(5);
                plan.setToolTopK(3);
                plan.setReflectionTopK(1);
                plan.setReason("Default balanced retrieval strategy");
            }
        }

        // Adjust for domain-specific needs
        if ("kubernetes".equalsIgnoreCase(domain) || "devops".equalsIgnoreCase(domain)) {
            plan.setToolTopK(plan.getToolTopK() + 5);
            plan.setEpisodeTopK(plan.getEpisodeTopK() + 3);
        }

        // Adjust for token budget
        if (task.getConstraint().getMaxTokens() != null && task.getConstraint().getMaxTokens() < 8000) {
            plan.scaleDown(0.5);
        }

        log.info("RetrievalPlan: intent={}, domain={}, reason={}, schedule={}",
                intent.getValue(), domain, plan.getReason(), plan);
        return plan;
    }

    public static class RetrievalPlan {
        private int memoryTopK = 5;
        private int conversationTopK = 5;
        private int episodeTopK = 3;
        private int knowledgeTopK = 5;
        private int toolTopK = 3;
        private int reflectionTopK = 1;
        private String reason = "default";

        public void scaleDown(double factor) {
            memoryTopK = Math.max(1, (int) (memoryTopK * factor));
            conversationTopK = Math.max(1, (int) (conversationTopK * factor));
            episodeTopK = Math.max(1, (int) (episodeTopK * factor));
            knowledgeTopK = Math.max(1, (int) (knowledgeTopK * factor));
            toolTopK = Math.max(1, (int) (toolTopK * factor));
            reflectionTopK = Math.max(1, (int) (reflectionTopK * factor));
        }

        // Getters and setters
        public int getMemoryTopK() { return memoryTopK; }
        public void setMemoryTopK(int v) { this.memoryTopK = v; }
        public int getConversationTopK() { return conversationTopK; }
        public void setConversationTopK(int v) { this.conversationTopK = v; }
        public int getEpisodeTopK() { return episodeTopK; }
        public void setEpisodeTopK(int v) { this.episodeTopK = v; }
        public int getKnowledgeTopK() { return knowledgeTopK; }
        public void setKnowledgeTopK(int v) { this.knowledgeTopK = v; }
        public int getToolTopK() { return toolTopK; }
        public void setToolTopK(int v) { this.toolTopK = v; }
        public int getReflectionTopK() { return reflectionTopK; }
        public void setReflectionTopK(int v) { this.reflectionTopK = v; }
        public String getReason() { return reason; }
        public void setReason(String v) { this.reason = v; }

        @Override
        public String toString() {
            return String.format("mem=%d, conv=%d, ep=%d, know=%d, tool=%d, ref=%d",
                    memoryTopK, conversationTopK, episodeTopK, knowledgeTopK, toolTopK, reflectionTopK);
        }
    }
}
