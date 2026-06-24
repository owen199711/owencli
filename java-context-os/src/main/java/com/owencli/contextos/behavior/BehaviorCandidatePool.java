package com.owencli.contextos.behavior;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * Behavior Candidate Pool — accumulates behavior observations over time.
 * <p>
 * Candidates are promoted to LearnedBehaviorMemory only after reaching thresholds:
 * <ul>
 *   <li>count >= 3</li>
 *   <li>confidence >= 0.70</li>
 *   <li>successRate >= 0.60</li>
 * </ul>
 * <p>
 * Old, low-confidence candidates are automatically evicted after 30 days.
 */
public class BehaviorCandidatePool {

    private static final Logger log = LoggerFactory.getLogger(BehaviorCandidatePool.class);

    private final Map<String, BehaviorCandidate> pool = new ConcurrentHashMap<>();

    // Consolidation thresholds
    private static final int MIN_COUNT = 3;
    private static final double MIN_CONFIDENCE = 0.70;
    private static final double MIN_SUCCESS_RATE = 0.60;
    private static final long EVICT_DAYS = 30;

    // Preference threshold: 3+ occurrences and >=60% in recent 10
    private static final int PREFERENCE_MIN_COUNT = 3;
    private static final double PREFERENCE_MIN_RATIO = 0.60;

    public BehaviorCandidatePool() {
        log.info("BehaviorCandidatePool initialized (minCount={}, minConfidence={})",
                MIN_COUNT, MIN_CONFIDENCE);
    }

    /**
     * Record an observation. Creates or updates a candidate.
     *
     * @return true if the candidate is ready for consolidation (met thresholds)
     */
    public boolean observe(String behaviorKey, String type, String description, boolean success) {
        var candidate = pool.computeIfAbsent(behaviorKey,
                k -> new BehaviorCandidate(type, behaviorKey, description));
        candidate.observe(success);
        log.debug("Behavior observed: {} (count={}, confidence={:.2f}, successRate={:.2f})",
                behaviorKey, candidate.getCount(), candidate.getConfidence(), candidate.getSuccessRate());
        return candidate.isReadyForConsolidation();
    }

    /**
     * Get all candidates ready for consolidation.
     */
    public List<BehaviorCandidate> getReadyCandidates() {
        return pool.values().stream()
                .filter(BehaviorCandidate::isReadyForConsolidation)
                .collect(Collectors.toList());
    }

    /**
     * Remove a candidate after consolidation.
     */
    public void remove(String behaviorKey) {
        pool.remove(behaviorKey);
        log.info("Candidate removed after consolidation: {}", behaviorKey);
    }

    /**
     * Run maintenance: apply decay + evict stale candidates.
     */
    public void runMaintenance() {
        Instant now = Instant.now();
        var toRemove = new ArrayList<String>();

        for (var entry : pool.entrySet()) {
            var c = entry.getValue();
            c.applyDecay();

            // Evict candidates older than EVICT_DAYS with low confidence
            if (Duration.between(c.getCreatedAt(), now).toDays() > EVICT_DAYS
                    && c.getConfidence() < 0.3) {
                toRemove.add(entry.getKey());
            }
        }

        toRemove.forEach(pool::remove);
        if (!toRemove.isEmpty()) {
            log.info("Pool maintenance: evicted {} stale candidates", toRemove.size());
        }
    }

    /**
     * Get all candidates (for inspection/debug).
     */
    public List<BehaviorCandidate> getAllCandidates() {
        return List.copyOf(pool.values());
    }

    public int size() { return pool.size(); }

    // Threshold accessors
    public static int getMinCount() { return MIN_COUNT; }
    public static double getMinConfidence() { return MIN_CONFIDENCE; }
    public static double getMinSuccessRate() { return MIN_SUCCESS_RATE; }
    public static int getPreferenceMinCount() { return PREFERENCE_MIN_COUNT; }
    public static double getPreferenceMinRatio() { return PREFERENCE_MIN_RATIO; }
}
