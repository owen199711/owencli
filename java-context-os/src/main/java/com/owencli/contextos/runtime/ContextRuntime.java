package com.owencli.contextos.runtime;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Context Runtime — manages the agent's execution loop.
 * <p>
 * Architecture:
 * <pre>
 *                 Context Runtime
 *                 ┌──────────────┐
 *                 │ Agent State  │
 *                 ├──────────────┤
 *                 │ Task Graph   │
 *                 ├──────────────┤
 *                 │ Observation  │
 *                 ├──────────────┤
 *                 │ Tool Result  │
 *                 ├──────────────┤
 *                 │ Retry Policy │
 *                 ├──────────────┤
 *                 │ Checkpoint   │
 *                 └──────────────┘
 * </pre>
 */
public class ContextRuntime {

    private static final Logger log = LoggerFactory.getLogger(ContextRuntime.class);

    private final AgentState agentState;
    private final TaskGraph taskGraph;
    private final Observation observation;
    private final Checkpoint checkpoint;
    private final RetryPolicy retryPolicy;

    public ContextRuntime() {
        this.agentState = new AgentState();
        this.taskGraph = new TaskGraph();
        this.observation = new Observation();
        this.checkpoint = new Checkpoint();
        this.retryPolicy = new RetryPolicy();
        log.info("ContextRuntime initialized");
    }

    public ContextRuntime(AgentState agentState, TaskGraph taskGraph,
                          Observation observation, Checkpoint checkpoint,
                          RetryPolicy retryPolicy) {
        this.agentState = agentState;
        this.taskGraph = taskGraph;
        this.observation = observation;
        this.checkpoint = checkpoint;
        this.retryPolicy = retryPolicy;
        log.info("ContextRuntime initialized with custom components");
    }

    public AgentState getAgentState() { return agentState; }
    public TaskGraph getTaskGraph() { return taskGraph; }
    public Observation getObservation() { return observation; }
    public Checkpoint getCheckpoint() { return checkpoint; }
    public RetryPolicy getRetryPolicy() { return retryPolicy; }

    /**
     * Execute a task through the runtime loop: THINK → OBSERVE → ACT → EVALUATE.
     */
    public <T> CompletableFuture<T> execute(RuntimeTask<T> task) {
        agentState.transitionTo("THINKING", "Starting task execution");
        try {
            return task.execute(this)
                    .thenApply(result -> {
                        agentState.transitionTo("EVALUATING", "Task completed");
                        agentState.transitionTo("IDLE", "Ready for next task");
                        return result;
                    });
        } catch (Exception e) {
            agentState.transitionTo("ERROR", "Task failed: " + e.getMessage());
            return CompletableFuture.failedFuture(e);
        }
    }

    @FunctionalInterface
    public interface RuntimeTask<T> {
        CompletableFuture<T> execute(ContextRuntime runtime);
    }
}
