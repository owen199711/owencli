package com.owencli.contextos.importances;

/**
 * Storage tier for memory — determined by final importance score.
 * <p>
 * Each tier defines: where to store, TTL, whether to vectorize, whether to summarize.
 * <pre>
 *  Score Range     Storage Tier           TTL       Embedding   Summary
 *  ≥ 0.90         FACT_SEMANTIC         永久        ✅          ❌
 *  0.75 ~ 0.90    EPISODE_LTM           永久        ✅          可选
 *  0.50 ~ 0.75    CONVERSATION_MED      7~30天     可选         ✅
 *  0.20 ~ 0.50    SHORT_TERM            24小时      ❌          ❌
 *  < 0.20         DISCARD               -          ❌          ❌
 * </pre>
 */
public enum StorageTier {
    FACT_SEMANTIC("fact_semantic", 1.0, true, false, -1),
    EPISODE_LTM("episode_ltm", 0.75, true, true, -1),
    CONVERSATION_MED("conversation_medium", 0.50, false, true, 14 * 24 * 3600),   // 14 days
    SHORT_TERM("short_term", 0.20, false, false, 24 * 3600),                        // 24 hours
    DISCARD("discard", 0.0, false, false, 0);

    private final String name;
    private final double minScore;
    private final boolean doEmbedding;
    private final boolean doSummary;
    private final int ttlSeconds; // -1 = permanent

    StorageTier(String name, double minScore, boolean doEmbedding, boolean doSummary, int ttlSeconds) {
        this.name = name;
        this.minScore = minScore;
        this.doEmbedding = doEmbedding;
        this.doSummary = doSummary;
        this.ttlSeconds = ttlSeconds;
    }

    public static StorageTier fromScore(double score) {
        for (var tier : values()) {
            if (score >= tier.minScore) return tier;
        }
        return DISCARD;
    }

    public String getName() { return name; }
    public double getMinScore() { return minScore; }
    public boolean isDoEmbedding() { return doEmbedding; }
    public boolean isDoSummary() { return doSummary; }
    public int getTtlSeconds() { return ttlSeconds; }
    public boolean isPermanent() { return ttlSeconds < 0; }
}
