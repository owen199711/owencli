package com.owencli.contextos.runtime;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * Observation — captures observations from tool execution and environment feedback.
 * Forms the basis for the agent's perception cycle.
 */
public class Observation {

    private static final Logger log = LoggerFactory.getLogger(Observation.class);

    private final Queue<ObservationEvent> events = new ConcurrentLinkedQueue<>();

    public void record(String source, String type, String content, Map<String, Object> metadata) {
        var event = new ObservationEvent(source, type, content, metadata, System.currentTimeMillis());
        events.add(event);
        log.info("Observation recorded: source={}, type={}", source, type);
    }

    public void recordToolResult(String toolName, boolean success, String output, long durationMs) {
        record("tool:" + toolName, success ? "success" : "failure",
                output, Map.of("duration_ms", durationMs));
    }

    public List<ObservationEvent> getRecent(int count) {
        var all = new ArrayList<>(events);
        if (all.size() <= count) return all;
        return all.subList(all.size() - count, all.size());
    }

    public List<ObservationEvent> getBySource(String source) {
        return events.stream()
                .filter(e -> e.source().equals(source))
                .toList();
    }

    public void clear() {
        events.clear();
        log.info("Observations cleared");
    }

    public int size() { return events.size(); }

    public record ObservationEvent(String source, String type, String content,
                                    Map<String, Object> metadata, long timestampMs) {}
}
