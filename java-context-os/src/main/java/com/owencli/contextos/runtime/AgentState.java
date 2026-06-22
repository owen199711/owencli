package com.owencli.contextos.runtime;

import com.owencli.contextos.core.model.TaskSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Agent State — tracks the current execution state of the agent.
 * Manages state transitions: IDLE → THINKING → OBSERVING → ACTING → EVALUATING.
 */
public class AgentState {

    private static final Logger log = LoggerFactory.getLogger(AgentState.class);

    private String currentState = "IDLE";
    private final Map<String, String> stateHistory = new ConcurrentHashMap<>();
    private final List<StateTransition> transitions = Collections.synchronizedList(new ArrayList<>());
    private String currentTaskId;

    public synchronized void transitionTo(String newState, String reason) {
        String from = this.currentState;
        this.currentState = newState;
        var transition = new StateTransition(from, newState, reason, System.currentTimeMillis());
        transitions.add(transition);
        stateHistory.put(newState, reason);
        log.info("Agent state: {} → {} ({})", from, newState, reason);
    }

    public synchronized String getCurrentState() { return currentState; }
    public String getCurrentTaskId() { return currentTaskId; }
    public void setCurrentTaskId(String taskId) { this.currentTaskId = taskId; }
    public List<StateTransition> getTransitions() { return List.copyOf(transitions); }
    public Map<String, String> getStateHistory() { return Map.copyOf(stateHistory); }

    public boolean isIdle() { return "IDLE".equals(currentState); }
    public boolean isThinking() { return "THINKING".equals(currentState); }
    public boolean isActing() { return "ACTING".equals(currentState); }
    public boolean isObserving() { return "OBSERVING".equals(currentState); }

    public record StateTransition(String from, String to, String reason, long timestampMs) {}
}
