package com.owencli.contextos.runtime;

import com.owencli.contextos.core.model.TaskSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Task Graph — tracks the execution graph of tasks and their dependencies.
 * Enables the agent to understand what has been done and what's next.
 */
public class TaskGraph {

    private static final Logger log = LoggerFactory.getLogger(TaskGraph.class);

    private final List<TaskNode> nodes = new CopyOnWriteArrayList<>();
    private final Map<String, List<String>> adjacency = new LinkedHashMap<>();

    public synchronized String addNode(TaskSpec task, String status) {
        String nodeId = task.getId();
        nodes.add(new TaskNode(nodeId, task.getRawInput(), task.getIntent().getValue(), status, System.currentTimeMillis()));
        adjacency.putIfAbsent(nodeId, new ArrayList<>());
        log.info("TaskGraph: added node {}", nodeId);
        return nodeId;
    }

    public synchronized void addDependency(String fromId, String toId) {
        adjacency.computeIfAbsent(fromId, k -> new ArrayList<>()).add(toId);
        log.debug("TaskGraph: dependency {} → {}", fromId, toId);
    }

    public synchronized void updateStatus(String nodeId, String status) {
        for (var node : nodes) {
            if (node.id().equals(nodeId)) {
                nodes.set(nodes.indexOf(node), new TaskNode(nodeId, node.description(), node.intent(), status, node.timestampMs()));
                log.info("TaskGraph: node {} status → {}", nodeId, status);
                return;
            }
        }
    }

    public synchronized List<TaskNode> getPending() {
        return nodes.stream().filter(n -> "PENDING".equals(n.status())).toList();
    }

    public synchronized List<TaskNode> getCompleted() {
        return nodes.stream().filter(n -> "COMPLETED".equals(n.status())).toList();
    }

    public synchronized List<TaskNode> getAllNodes() { return List.copyOf(nodes); }

    public record TaskNode(String id, String description, String intent, String status, long timestampMs) {}
}
