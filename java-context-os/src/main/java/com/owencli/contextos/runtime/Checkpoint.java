package com.owencli.contextos.runtime;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Checkpoint — saves and restores execution checkpoints for long-running tasks.
 * Enables recovery from failures without restarting from scratch.
 */
public class Checkpoint {

    private static final Logger log = LoggerFactory.getLogger(Checkpoint.class);

    private final Map<String, CheckpointData> store = new ConcurrentHashMap<>();

    public String save(String taskId, String phase, Map<String, Object> data) {
        String checkpointId = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        store.put(checkpointId, new CheckpointData(taskId, phase, data, System.currentTimeMillis()));
        log.info("Checkpoint saved: id={}, task={}, phase={}", checkpointId, taskId, phase);
        return checkpointId;
    }

    public Optional<CheckpointData> restore(String checkpointId) {
        var data = store.get(checkpointId);
        if (data == null) {
            log.warn("Checkpoint not found: {}", checkpointId);
            return Optional.empty();
        }
        log.info("Checkpoint restored: id={}, task={}, phase={}", checkpointId, data.taskId(), data.phase());
        return Optional.of(data);
    }

    public List<CheckpointData> getTaskCheckpoints(String taskId) {
        return store.values().stream()
                .filter(c -> c.taskId().equals(taskId))
                .sorted(Comparator.comparingLong(CheckpointData::timestampMs).reversed())
                .toList();
    }

    public void delete(String checkpointId) {
        store.remove(checkpointId);
        log.info("Checkpoint deleted: {}", checkpointId);
    }

    public void clear() {
        store.clear();
        log.info("All checkpoints cleared");
    }

    public record CheckpointData(String taskId, String phase, Map<String, Object> data, long timestampMs) {}
}
