package com.owencli.contextos.pipeline;

import com.owencli.contextos.builder.ContextBuilder;
import com.owencli.contextos.builder.ContextMerger;
import com.owencli.contextos.collection.ConversationCollector;
import com.owencli.contextos.collection.EnvironmentCollector;
import com.owencli.contextos.collection.IdentityCollector;
import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.config.ContextOsProperties;
import com.owencli.contextos.core.exception.ContextOSException;
import com.owencli.contextos.core.model.*;
import com.owencli.contextos.evolution.KnowledgeEvolution;
import com.owencli.contextos.feedback.MemoryUpdater;
import com.owencli.contextos.feedback.QualityEvaluator;
import com.owencli.contextos.feedback.Tracer;
import com.owencli.contextos.intent.EntityExtractor;
import com.owencli.contextos.intent.IntentClassifier;
import com.owencli.contextos.intent.TaskParser;
import com.owencli.contextos.lifecycle.MemoryLifecycle;
import com.owencli.contextos.memory.*;
import com.owencli.contextos.optimizer.ContextCompressor;
import com.owencli.contextos.optimizer.ContextOptimizer;
import com.owencli.contextos.optimizer.RelevanceRanker;
import com.owencli.contextos.optimizer.TokenBudgetAllocator;
import com.owencli.contextos.orchestrator.ContextRouter;
import com.owencli.contextos.orchestrator.ContextSelector;
import com.owencli.contextos.packager.ContextPackager;
import com.owencli.contextos.policy.ContextPolicy;
import com.owencli.contextos.reflection.ReflectionEngine;
import com.owencli.contextos.runtime.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/**
 * Context-OS main Pipeline orchestrator (v2.0 upgraded architecture).
 * <p>
 * Execution flow:
 * <pre>
 * Intent → Orchestrator → Collection → Builder → Optimizer → Packager → LLM → Feedback → Reflection
 * </pre>
 * <p>
 * Full component architecture:
 * <pre>
 *                         User
 *                           │
 *                           ▼
 *                   Intent Understanding
 *                           │
 *                           ▼
 *                   Context Operating System
 *  ──────────────────────────────────────────────────────
 *   Identity Manager    Session Manager    Environment Manager
 *
 *   Memory Manager
 *     ├── Working
 *     ├── Conversation
 *     ├── Task
 *     ├── Long-term
 *     ├── Episodic
 *     ├── Semantic
 *     ├── Procedural
 *     ├── Reflection
 *     └── Tool Experience
 *
 *   Retrieval Planner   Context Builder   Context Fusion
 *   Context Optimizer   Prompt Packager
 *
 *   Runtime Manager
 *     ├── Agent State
 *     ├── Task Graph
 *     ├── Observation
 *     ├── Checkpoint
 *     ├── Retry Policy
 *     └── Execution Context
 *
 *   Knowledge Evolution   Memory Lifecycle   Context Policy
 *   Tool Learning
 * </pre>
 */
public class ContextOSPipeline {

    private static final Logger log = LoggerFactory.getLogger(ContextOSPipeline.class);

    private final String sessionId;
    private final String userId;
    private final LLMProvider provider;

    // Storage
    private final SQLiteStore store;
    private boolean storeConnected = false;

    // Intent
    private final TaskParser taskParser;

    // Orchestrator
    private final ContextSelector selector;
    private final ContextRouter router;

    // Collection
    private final IdentityCollector identityCollector;
    private final ConversationCollector conversationCollector;
    private final EnvironmentCollector environmentCollector;

    // Memory Manager (unified facade over all memory subsystems)
    private final MemoryManager memoryManager;

    // Builder
    private final ContextBuilder builder;

    // Optimizer
    private final ContextOptimizer optimizer;

    // Packager
    private final ContextPackager packager;

    // Feedback
    private final QualityEvaluator evaluator;
    private final Tracer tracer;
    private final MemoryUpdater memoryUpdater;
    private final ReflectionEngine reflectionEngine;

    // Behavior Pipeline (last layer — detects patterns across episodes)
    private final com.owencli.contextos.behavior.BehaviorPipeline behaviorPipeline;

    // Runtime
    private final ContextRuntime runtime;

    // Lifecycle & Evolution
    private final MemoryLifecycle memoryLifecycle;
    private final KnowledgeEvolution knowledgeEvolution;

    // Policy
    private final ContextPolicy contextPolicy;

    // LLM
    private final BaseLLMClient llmClient;

    public ContextOSPipeline(BaseLLMClient llmClient, LLMProvider provider,
                             String dbPath, String sessionId, String userId) {
        this.sessionId = sessionId != null ? sessionId : UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        this.userId = userId != null ? userId : "anonymous";
        this.provider = provider;
        this.llmClient = llmClient;

        // Storage
        this.store = new SQLiteStore(dbPath);

        // Intent
        var classifier = new IntentClassifier(llmClient);
        var extractor = new EntityExtractor();
        this.taskParser = new TaskParser(classifier, extractor);

        // Orchestrator
        this.selector = new ContextSelector();
        this.router = new ContextRouter();

        // Collection
        this.identityCollector = new IdentityCollector();
        this.conversationCollector = new ConversationCollector();
        this.environmentCollector = new EnvironmentCollector();

        // Memory — 7 subsystems + LongTermIndex
        var embeddingConfig = new ContextOsProperties.Embedding();
        var embeddingFactory = new EmbeddingServiceFactory(embeddingConfig);
        var embeddingService = embeddingFactory.create();
        var workingMemory = new WorkingMemory();
        var conversationMemory = new ConversationMemory(this.sessionId, this.store);
        var longTermMemory = new LongTermMemory(this.store, this.userId, embeddingService);
        var episodicMemory = new EpisodicMemory(this.store, this.userId);
        var semanticMemory = new SemanticMemory(this.store, this.userId);
        var learnedBehaviorMemory = new LearnedBehaviorMemory(this.store, this.userId);
        var factMemory = new FactMemory(this.store, this.userId);
        var longTermIndex = new LongTermIndex(longTermMemory, episodicMemory, semanticMemory);

        this.memoryManager = new MemoryManager(
                workingMemory, conversationMemory,
                episodicMemory, semanticMemory,
                factMemory, learnedBehaviorMemory,
                longTermMemory, longTermIndex
        );

        // Builder
        var merger = new ContextMerger();
        this.builder = new ContextBuilder(selector, router, identityCollector,
                conversationCollector, environmentCollector, memoryManager, merger);

        // Optimizer
        var ranker = new RelevanceRanker();
        var compressor = new ContextCompressor(llmClient);
        var budget = new TokenBudgetAllocator();
        this.optimizer = new ContextOptimizer(ranker, compressor, budget);

        // Packager
        this.packager = new ContextPackager();

        // Runtime (needed by MemoryUpdater for TaskGraph)
        this.runtime = new ContextRuntime();

        // Feedback
        this.evaluator = new QualityEvaluator(llmClient);
        this.tracer = new Tracer();
        this.memoryUpdater = new MemoryUpdater(
                workingMemory, conversationMemory, learnedBehaviorMemory,
                longTermMemory, episodicMemory, semanticMemory,
                llmClient, factMemory, embeddingService,
                runtime.getTaskGraph(), false
        );
        this.reflectionEngine = new ReflectionEngine(learnedBehaviorMemory, llmClient);

        // Behavior Pipeline (learned patterns from episodes)
        this.behaviorPipeline = new com.owencli.contextos.behavior.BehaviorPipeline(learnedBehaviorMemory);

        // Lifecycle & Evolution
        this.memoryLifecycle = new MemoryLifecycle(store);
        this.knowledgeEvolution = new KnowledgeEvolution(semanticMemory, store);

        // Policy
        this.contextPolicy = new ContextPolicy();

        log.info("ContextOSPipeline v2.0 initialized: session={}, user={}, provider={}",
                this.sessionId, this.userId, this.provider.getValue());
        log.info("Memory subsystems: working, conversation, episodic, semantic, fact, learned_behavior, long_term");
        log.info("LongTermIndex: global vector retrieval layer (LTM + Episodic + Semantic)");
        log.info("Lifecycle: archive={}d, forget={}d", 30, 90);
    }

    public CompletableFuture<Void> ensureStore() {
        if (!storeConnected) {
            return store.connect().thenAccept(v -> storeConnected = true);
        }
        return CompletableFuture.completedFuture(null);
    }

    /**
     * Execute the full Context Pipeline v2.0.
     *
     * @param userInput User input text.
     * @return Map with keys: response, metrics, trace_id, task_spec, latency_ms.
     */
    public CompletableFuture<Map<String, Object>> run(String userInput) {
        return ensureStore().thenCompose(v -> {
            conversationCollector.addTurn("user", userInput);

            var tracerId = tracer.start("", userInput);
            log.info("========== Pipeline v2.0 start ==========");
            log.info("input: {}...", truncate(userInput, 120));

            long pipelineStart = System.currentTimeMillis();

            try {
                // ── Step 1: Intent Understanding ──
                var s1 = tracer.stepBegin("intent_understanding");
                CompletableFuture<TaskSpec> taskFuture = taskParser.parse(userInput);

                return taskFuture.thenCompose(task -> {
                    tracer.stepEnd(s1, userInput, task.getIntent().getValue());
                    log.info("Step 1 (意图理解): intent={}, goal={}, confidence={}",
                            task.getIntent().getValue(), task.getGoal().getValue(), task.getConfidence());

                    // Apply Context Policy
                    var policyDirective = contextPolicy.evaluate(task);
                    log.info("Policy: rule={}, skipKnowledge={}, skipTools={}",
                            policyDirective.getMatchedRule(),
                            policyDirective.isSkipKnowledge(),
                            policyDirective.isSkipTools());

                    // ── Step 2: Context Building (with Retrieval Planner + Policy Directive) ──
                    var s2 = tracer.stepBegin("context_building");
                    return builder.build(task, policyDirective).thenCompose(unified -> {
                        tracer.stepEnd(s2, task.getId(), "memory=" + unified.getMemory().size());
                        log.info("Step 2 (上下文构建): memory={}, knowledge={}", unified.getMemory().size(), unified.getKnowledge().size());

                        // ── Step 3: Context Optimization ──
                        var s3 = tracer.stepBegin("context_optimization");
                        return optimizer.optimize(unified, task).thenCompose(optimized -> {
                            tracer.stepEnd(s3, "memories=" + unified.getMemory().size(),
                                    "budget=" + optimized.getTokenUsage().getTotal());
                            log.info("Step 3 (上下文优化): compressed={}, budget={}, used={}",
                                    optimized.isCompressed(), optimized.getTokenUsage().getTotal(),
                                    optimized.getTokenUsage().getUsed());

                            // ── Step 4: Context Packaging ──
                            var s4 = tracer.stepBegin("context_packaging");
                            var packaged = packager.pack(optimized, provider);
                            tracer.stepEnd(s4, provider.getValue(),
                                    "prompt_len=" + packaged.getRawPrompt().length());
                            log.info("Step 4 (Prompt 打包): provider={}, prompt_len={} chars",
                                    provider.getValue(), packaged.getRawPrompt().length());

                            // ── Step 5: LLM Inference ──
                            var s5 = tracer.stepBegin("llm_inference");
                            long t0 = System.currentTimeMillis();
                            return llmClient.complete(packaged.getRawPrompt()).thenCompose(llmResponse -> {
                                double llmLatency = (System.currentTimeMillis() - t0);
                                tracer.stepEnd(s5, truncate(packaged.getRawPrompt(), 200),
                                        truncate(String.valueOf(llmResponse), 300));

                                String responseStr = String.valueOf(llmResponse);
                                log.info("Step 5 (LLM 推理): latency={:.0f}ms, response_len={}",
                                        llmLatency, responseStr.length());

                                conversationCollector.addTurn("assistant", truncate(responseStr, 5000));

                                // ── Step 6: Feedback & Memory Update ──
                                var s6 = tracer.stepBegin("feedback");
                                int tokenEstimate = optimized.getTokenUsage().getUsed() != 0 ?
                                        optimized.getTokenUsage().getUsed() :
                                        packaged.getRawPrompt().length() / 4;

                                return evaluator.evaluate(packaged, responseStr, llmLatency, tokenEstimate)
                                        .thenCompose(metrics -> {
                                            tracer.stepEnd(s6, truncate(packaged.getRawPrompt(), 100),
                                                    String.valueOf(metrics.isSuccess()));

                                            // MemoryUpdater (pipeline: Extract → Score → Conflict → Dedup → Write)
                                            return memoryUpdater.updateFromTask(task, responseStr, metrics, userId)
                                                    .thenCompose(memResult -> {
                                                        // ── Step 7: Reflection (post-task learning) ──
                                                        return reflectionEngine.reflect(
                                                                        task, responseStr, metrics.isSuccess(),
                                                                        metrics.isSuccess() ? null : "failure detected",
                                                                        userId)
                                                                .thenCompose(ignored2 -> {
                                                                    // ── Step 8: Background maintenance ──
                                                                    // Consolidate LTM (remove duplicates)
                                                                    return memoryManager.getLongTerm().consolidate()
                                                                            .thenAccept(count -> {
                                                                                if (count > 0) log.info("LTM consolidate: removed {} duplicates", count);
                                                                            });
                                                                })
                                                                .thenCompose(ignored3 -> {
                                                                    // ── Step 9: Behavior Detection ──
                                                                    // Analyze episode for pattern learning (last layer of pipeline)
                                                                    var episode = new com.owencli.contextos.core.model.EpisodeInfo();
                                                                    episode.setIntent(task.getIntent().getValue());
                                                                    episode.setUserInput(task.getRawInput());
                                                                    episode.setResponse(responseStr);
                                                                    episode.setSuccess(metrics.isSuccess());
                                                                    return behaviorPipeline.processEpisode(episode);
                                                                })
                                                                .thenApply(behaviorsLearned -> {
                                                                    tracer.finish(metrics.isSuccess());

                                                                    double totalLatency = (System.currentTimeMillis() - pipelineStart);
                                                                    log.info("========== Pipeline v2.0 end: success={}, total={:.0f}ms ==========",
                                                                            metrics.isSuccess(), totalLatency);

                                                                    Map<String, Object> result = new HashMap<>();
                                                                    result.put("response", responseStr);
                                                                    result.put("metrics", metrics);
                                                                    result.put("trace_id", tracerId);
                                                                    result.put("task_spec", task);
                                                                    result.put("memory_update", memResult);
                                                                    result.put("behaviors_learned", behaviorsLearned);
                                                                    result.put("latency_ms", Math.round(totalLatency * 10.0) / 10.0);
                                                                    result.put("unified_context", unified);
                                                                    result.put("optimized_context", optimized);
                                                                    result.put("packaged_context", packaged);
                                                                    return result;
                                                                });
                                                    });
                                        });
                            });
                        });
                    });
                });

            } catch (Exception e) {
                log.error("Pipeline error: {}", e.getMessage(), e);
                tracer.finish(false);
                return CompletableFuture.failedFuture(
                        new ContextOSException("Pipeline execution failed: " + e.getMessage(), e));
            }
        });
    }

    /**
     * Run background maintenance (memory lifecycle + knowledge evolution).
     */
    public CompletableFuture<Void> runMaintenance() {
        log.info("Starting background maintenance...");
        return memoryLifecycle.runMaintenance()
                .thenCompose(v -> knowledgeEvolution.evolve())
                .thenRun(() -> log.info("Background maintenance complete"));
    }

    public ConversationCollector getConversationCollector() {
        return conversationCollector;
    }

    public WorkingMemory getWorkingMemory() {
        return memoryManager.getWorking();
    }

    public MemoryManager getMemoryManager() {
        return memoryManager;
    }

    public ContextRuntime getRuntime() {
        return runtime;
    }

    public MemoryLifecycle getMemoryLifecycle() {
        return memoryLifecycle;
    }

    public KnowledgeEvolution getKnowledgeEvolution() {
        return knowledgeEvolution;
    }

    public ReflectionEngine getReflectionEngine() {
        return reflectionEngine;
    }

    /**
     * Close the pipeline, releasing resources.
     */
    public CompletableFuture<Void> close() {
        return store.close().thenRun(() -> log.info("Pipeline closed"));
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }

    // Builder pattern for pipeline creation
    public static class Builder {
        private BaseLLMClient llmClient;
        private LLMProvider provider = LLMProvider.DEEPSEEK;
        private String dbPath = "./data/context_os.db";
        private String sessionId;
        private String userId = "anonymous";

        public Builder llmClient(BaseLLMClient client) { this.llmClient = client; return this; }
        public Builder provider(LLMProvider p) { this.provider = p; return this; }
        public Builder dbPath(String path) { this.dbPath = path; return this; }
        public Builder sessionId(String id) { this.sessionId = id; return this; }
        public Builder userId(String id) { this.userId = id; return this; }

        public ContextOSPipeline build() {
            if (llmClient == null) {
                throw new IllegalArgumentException("llmClient is required");
            }
            return new ContextOSPipeline(llmClient, provider, dbPath, sessionId, userId);
        }
    }
}
