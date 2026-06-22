package com.owencli.contextos.importances;

import com.owencli.contextos.runtime.TaskGraph;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Goal Relation Scorer — checks if the current content relates to an ongoing goal.
 * <p>
 * If the user has been working on "Context-OS" and now talks about "Memory Manager",
 * that's goal-related and should score higher.
 * <p>
 * Uses the TaskGraph to find recent/pending task descriptions and checks
 * for keyword overlap with the current content.
 * <p>
 * Weight in final score: 0.10.
 */
public class GoalRelationScorer {

    private static final Logger log = LoggerFactory.getLogger(GoalRelationScorer.class);

    private final TaskGraph taskGraph;

    public GoalRelationScorer(TaskGraph taskGraph) {
        this.taskGraph = taskGraph;
    }

    public double score(String input) {
        if (input == null || input.isBlank()) return 0.0;

        var allNodes = taskGraph.getAllNodes();
        if (allNodes.isEmpty()) return 0.5; // No task history → neutral

        String inputLower = input.toLowerCase();
        double maxOverlap = 0.0;

        for (var node : allNodes) {
            String desc = node.description() != null ? node.description().toLowerCase() : "";
            if (desc.isBlank()) continue;

            double overlap = computeKeywordOverlap(inputLower, desc);
            if (overlap > maxOverlap) maxOverlap = overlap;
        }

        // Boost if overlap found
        return Math.min(1.0, maxOverlap * 1.5);
    }

    private double computeKeywordOverlap(String input, String taskDesc) {
        var inputTokens = new java.util.LinkedHashSet<>(
                java.util.List.of(input.split("[^a-zA-Z0-9\\u4e00-\\u9fff]+")));
        var descTokens = new java.util.LinkedHashSet<>(
                java.util.List.of(taskDesc.split("[^a-zA-Z0-9\\u4e00-\\u9fff]+")));

        // Filter to meaningful tokens
        inputTokens.removeIf(w -> w.length() < 2);
        descTokens.removeIf(w -> w.length() < 2);

        if (inputTokens.isEmpty() || descTokens.isEmpty()) return 0.0;

        var intersection = new java.util.LinkedHashSet<>(inputTokens);
        intersection.retainAll(descTokens);

        var union = new java.util.LinkedHashSet<>(inputTokens);
        union.addAll(descTokens);

        return (double) intersection.size() / union.size();
    }
}
