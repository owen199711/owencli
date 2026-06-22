package com.owencli.contextos.importances;

/**
 * Multi-dimensional memory importance result.
 * <p>
 * Instead of a single score + 0.75 threshold, this captures all 9 scoring dimensions
 * plus the computed final score and storage tier assignment.
 */
public class MemoryImportanceResult {

    // ── 9 scoring dimensions ──
    private final double ruleScore;           // Factor 1-5: length, code, error, entities
    private final double semanticScore;       // Factor 6: LLM-based importance judge
    private final double noveltyScore;        // Factor 7: is this information new?
    private final double factWeightScore;     // Factor 8: fact type weight (identity=1.0, temp=0.2)
    private final double goalRelationScore;   // Factor 9: alignment with current task goals
    private final double noveltyEntityScore;  // New entity count (first-time mention)
    private final double reusabilityScore;    // Will this be referenced again?
    private final double emotionScore;        // Emotional significance
    private final double taskCompletionScore; // Task lifecycle stage

    // ── Derived ──
    private final double finalScore;
    private final StorageTier storageTier;
    private final String summary;

    public MemoryImportanceResult(double ruleScore, double semanticScore, double noveltyScore,
                                   double factWeightScore, double goalRelationScore,
                                   double noveltyEntityScore, double reusabilityScore,
                                   double emotionScore, double taskCompletionScore,
                                   String summary) {
        this.ruleScore = ruleScore;
        this.semanticScore = semanticScore;
        this.noveltyScore = noveltyScore;
        this.factWeightScore = factWeightScore;
        this.goalRelationScore = goalRelationScore;
        this.noveltyEntityScore = noveltyEntityScore;
        this.reusabilityScore = reusabilityScore;
        this.emotionScore = emotionScore;
        this.taskCompletionScore = taskCompletionScore;

        // Final = 0.20×Rule + 0.35×Semantic + 0.20×Novelty + 0.15×FactWeight + 0.10×GoalRelation
        this.finalScore = Math.min(1.0, Math.max(0.0,
                ruleScore * 0.20
                        + semanticScore * 0.35
                        + noveltyScore * 0.20
                        + factWeightScore * 0.15
                        + goalRelationScore * 0.10
        ));
        this.storageTier = StorageTier.fromScore(this.finalScore);
        this.summary = summary;
    }

    public double getRuleScore() { return ruleScore; }
    public double getSemanticScore() { return semanticScore; }
    public double getNoveltyScore() { return noveltyScore; }
    public double getFactWeightScore() { return factWeightScore; }
    public double getGoalRelationScore() { return goalRelationScore; }
    public double getNoveltyEntityScore() { return noveltyEntityScore; }
    public double getReusabilityScore() { return reusabilityScore; }
    public double getEmotionScore() { return emotionScore; }
    public double getTaskCompletionScore() { return taskCompletionScore; }
    public double getFinalScore() { return finalScore; }
    public StorageTier getStorageTier() { return storageTier; }
    public String getSummary() { return summary; }

    public boolean shouldDiscard() { return storageTier == StorageTier.DISCARD; }

    public String dimensionReport() {
        return String.format(
                "Rule=%.2f Semantic=%.2f Novelty=%.2f FactWt=%.2f Goal=%.2f → Final=%.2f → %s",
                ruleScore, semanticScore, noveltyScore, factWeightScore,
                goalRelationScore, finalScore, storageTier.getName()
        );
    }
}
