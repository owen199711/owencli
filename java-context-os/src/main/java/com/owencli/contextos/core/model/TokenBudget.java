package com.owencli.contextos.core.model;

import java.util.HashMap;
import java.util.Map;

public class TokenBudget {
    private int total = 0;
    private int used = 0;
    private Map<String, Integer> breakdown = new HashMap<>();

    public int getTotal() { return total; }
    public void setTotal(int total) { this.total = total; }
    public int getUsed() { return used; }
    public void setUsed(int used) { this.used = used; }
    public Map<String, Integer> getBreakdown() { return breakdown; }
    public void setBreakdown(Map<String, Integer> breakdown) { this.breakdown = breakdown; }
}
