package com.owencli.contextos.core.model;

public class KnowledgeRequirement {
    private String domain;
    private String query;
    private int topK = 5;

    public KnowledgeRequirement() {}

    public KnowledgeRequirement(String domain, String query, int topK) {
        this.domain = domain;
        this.query = query;
        this.topK = topK;
    }

    public String getDomain() { return domain; }
    public void setDomain(String domain) { this.domain = domain; }
    public String getQuery() { return query; }
    public void setQuery(String query) { this.query = query; }
    public int getTopK() { return topK; }
    public void setTopK(int topK) { this.topK = topK; }
}
