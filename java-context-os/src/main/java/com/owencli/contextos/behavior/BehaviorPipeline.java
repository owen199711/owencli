package com.owencli.contextos.behavior;

import com.owencli.contextos.core.model.EpisodeInfo;
import com.owencli.contextos.memory.LearnedBehaviorMemory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;

/**
 * Behavior Pipeline — the last layer of the memory system.
 * <p>
 * Full pipeline:
 * <pre>
 *  Task Finished
 *        │
 *        ▼
 *  Importance Scorer
 *        │
 *   ┌────┴────┐
 *   ▼         ▼
 * Conversation  Episodic Memory
 *                    │
 *                    ▼
 *             Reflection Engine
 *                    │
 *                    ▼
 *            Behavior Detector
 *                    │
 *                    ▼
 *           Behavior Candidate Pool
 *                    │
 *          (Count + Confidence + Decay)
 *                    │
 *        >= 3 times + >= 0.70 confidence?
 *                    │
 *                    ▼
 *           Behavior Consolidator
 *                    │
 *                    ▼
 *          LearnedBehavior Memory
 * </pre>
 */
public class BehaviorPipeline {

    private static final Logger log = LoggerFactory.getLogger(BehaviorPipeline.class);

    private final BehaviorDetector detector;
    private final BehaviorCandidatePool pool;
    private final BehaviorConsolidator consolidator;
    private final LearnedBehaviorMemory learnedBehavior;

    private int episodeCount = 0;

    public BehaviorPipeline(LearnedBehaviorMemory learnedBehavior) {
        this.pool = new BehaviorCandidatePool();
        this.learnedBehavior = learnedBehavior;
        this.detector = new BehaviorDetector(pool, learnedBehavior);
        this.consolidator = new BehaviorConsolidator(pool, learnedBehavior);
        log.info("BehaviorPipeline initialized");
    }

    /**
     * Process a completed episode. Runs detection + periodic consolidation.
     */
    public CompletableFuture<Integer> processEpisode(EpisodeInfo episode) {
        if (episode == null) return CompletableFuture.completedFuture(0);

        // Step 1: Detect behavior patterns
        detector.analyzeEpisode(episode);
        episodeCount++;

        // Step 2: Periodically consolidate (every 5 episodes, or forced)
        if (episodeCount % 5 == 0 || episode.isSuccess()) {
            return consolidator.consolidate();
        }

        return CompletableFuture.completedFuture(0);
    }

    /**
     * Force consolidation of all ready candidates.
     */
    public CompletableFuture<Integer> forceConsolidate() {
        return consolidator.consolidate();
    }

    /**
     * Run pool maintenance (decay + eviction).
     */
    public void runMaintenance() {
        pool.runMaintenance();
    }

    public BehaviorCandidatePool getPool() { return pool; }
    public BehaviorDetector getDetector() { return detector; }
}
