package com.owencli.contextos.optimizer;

import com.owencli.contextos.core.model.TokenBudget;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Allocates token budget across context sections.
 */
public class TokenBudgetAllocator {

    private static final Logger log = LoggerFactory.getLogger(TokenBudgetAllocator.class);

    private static final int DEFAULT_TOTAL = 32000;
    private static final int MIN_TOTAL = 4000;
    private static final int MAX_TOTAL = 128000;

    private int totalTokens = DEFAULT_TOTAL;

    public void adjustForModel(int maxTokens) {
        this.totalTokens = Math.max(MIN_TOTAL, Math.min(MAX_TOTAL, maxTokens));
        log.debug("Token budget adjusted to {}", totalTokens);
    }

    public TokenBudget allocate() {
        var budget = new TokenBudget();
        budget.setTotal(totalTokens);
        budget.setUsed(0);

        var breakdown = budget.getBreakdown();
        breakdown.put("system", (int) (totalTokens * 0.1));
        breakdown.put("identity", (int) (totalTokens * 0.05));
        breakdown.put("conversation", (int) (totalTokens * 0.25));
        breakdown.put("environment", (int) (totalTokens * 0.05));
        breakdown.put("memory", (int) (totalTokens * 0.25));
        breakdown.put("knowledge", (int) (totalTokens * 0.15));
        breakdown.put("tools", (int) (totalTokens * 0.05));
        breakdown.put("instruction", (int) (totalTokens * 0.1));

        log.debug("Token budget allocated: total={}", totalTokens);
        return budget;
    }

    public int getTotalTokens() { return totalTokens; }
}
