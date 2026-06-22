package com.owencli.contextos.feedback;

import com.owencli.contextos.importances.StorageTier;

/**
 * Result of a MemoryUpdater pipeline execution.
 * Shows what happened during memory update: multi-dimensional importance scores,
 * storage tier assignment, which stores were written to, etc.
 */
public class MemoryUpdateResult {

    private final double ruleScore;
    private final double semanticScore;
    private final double noveltyScore;
    private final double factWeightScore;
    private final double goalRelationScore;
    private final double finalScore;
    private final StorageTier storageTier;
    private final boolean savedToLTM;
    private final boolean savedToEpisodic;
    private final boolean savedToSemantic;
    private final int factsSaved;
    private final boolean wasDuplicate;
    private final boolean hasConflict;
    private final long elapsedMs;

    public MemoryUpdateResult(double ruleScore, double semanticScore, double noveltyScore,
                              double factWeightScore, double goalRelationScore,
                              double finalScore, StorageTier storageTier,
                              boolean savedToLTM, boolean savedToEpisodic, boolean savedToSemantic,
                              int factsSaved, boolean wasDuplicate, boolean hasConflict,
                              long elapsedMs) {
        this.ruleScore = ruleScore;
        this.semanticScore = semanticScore;
        this.noveltyScore = noveltyScore;
        this.factWeightScore = factWeightScore;
        this.goalRelationScore = goalRelationScore;
        this.finalScore = finalScore;
        this.storageTier = storageTier;
        this.savedToLTM = savedToLTM;
        this.savedToEpisodic = savedToEpisodic;
        this.savedToSemantic = savedToSemantic;
        this.factsSaved = factsSaved;
        this.wasDuplicate = wasDuplicate;
        this.hasConflict = hasConflict;
        this.elapsedMs = elapsedMs;
    }

    public double getRuleScore() { return ruleScore; }
    public double getSemanticScore() { return semanticScore; }
    public double getNoveltyScore() { return noveltyScore; }
    public double getFactWeightScore() { return factWeightScore; }
    public double getGoalRelationScore() { return goalRelationScore; }
    public double getFinalScore() { return finalScore; }
    public double getImportanceScore() { return finalScore; }
    public StorageTier getStorageTier() { return storageTier; }
    public boolean isSavedToLTM() { return savedToLTM; }
    public boolean isSavedToEpisodic() { return savedToEpisodic; }
    public boolean isSavedToSemantic() { return savedToSemantic; }
    public int getFactsSaved() { return factsSaved; }
    public boolean isWasDuplicate() { return wasDuplicate; }
    public boolean isHasConflict() { return hasConflict; }
    public long getElapsedMs() { return elapsedMs; }

    public String summary() {
        var sb = new StringBuilder();
        sb.append(String.format("最终=%.2f → %s", finalScore, storageTier.getName()));
        sb.append(String.format(" (规则=%.2f 语义=%.2f 新颖=%.2f 事实=%.2f 目标=%.2f)",
                ruleScore, semanticScore, noveltyScore, factWeightScore, goalRelationScore));
        if (factsSaved > 0) sb.append(", 提取事实=" + factsSaved);
        if (wasDuplicate) sb.append(", 重复已合并");
        if (hasConflict) sb.append(", 有冲突");
        sb.append(String.format(", %dms", elapsedMs));
        return sb.toString();
    }
}
