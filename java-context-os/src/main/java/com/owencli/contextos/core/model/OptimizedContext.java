package com.owencli.contextos.core.model;

public class OptimizedContext {
    private boolean compressed = false;
    private TokenBudget tokenUsage = new TokenBudget();
    private UnifiedContext context;

    public boolean isCompressed() { return compressed; }
    public void setCompressed(boolean compressed) { this.compressed = compressed; }
    public TokenBudget getTokenUsage() { return tokenUsage; }
    public void setTokenUsage(TokenBudget tokenUsage) { this.tokenUsage = tokenUsage; }
    public UnifiedContext getContext() { return context; }
    public void setContext(UnifiedContext context) { this.context = context; }
}
