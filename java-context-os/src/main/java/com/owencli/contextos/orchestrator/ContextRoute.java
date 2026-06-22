package com.owencli.contextos.orchestrator;

/**
 * Context route — maps a ContextFlag to a data source with priority.
 */
public class ContextRoute {
    private final String source;
    private final ContextFlag flag;
    private final int priority;

    public ContextRoute(String source, ContextFlag flag, int priority) {
        this.source = source;
        this.flag = flag;
        this.priority = priority;
    }

    public String getSource() { return source; }
    public ContextFlag getFlag() { return flag; }
    public int getPriority() { return priority; }
}
