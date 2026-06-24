package com.owencli.contextos.builder;

import com.owencli.contextos.collection.ConversationCollector;
import com.owencli.contextos.collection.EnvironmentCollector;
import com.owencli.contextos.collection.IdentityCollector;
import com.owencli.contextos.core.exception.ContextBuildException;
import com.owencli.contextos.core.model.*;
import com.owencli.contextos.memory.*;
import com.owencli.contextos.orchestrator.ContextFlag;
import com.owencli.contextos.orchestrator.ContextRouter;
import com.owencli.contextos.orchestrator.ContextSelector;
import com.owencli.contextos.policy.ContextPolicy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Context Builder with Retrieval Planner integration.
 * <p>
 * Architecture:
 * <pre>
 *             Context Builder
 *                    │
 *                    ▼
 *            Retrieval Planner
 *                    │
 *       ┌────────────┼─────────────┐
 *       ▼            ▼             ▼
 *    Memory      Knowledge      Tool
 *       ▼            ▼             ▼
 *             Retrieval Fusion
 *                    ▼
 *            Relevance Ranking
 *                    ▼
 *               Context Merge
 * </pre>
 */
public class ContextBuilder {

    private static final Logger log = LoggerFactory.getLogger(ContextBuilder.class);

    private final ContextSelector selector;
    private final ContextRouter router;
    private final RetrievalPlanner planner;
    private final IdentityCollector identity;
    private final ConversationCollector conversation;
    private final EnvironmentCollector environment;
    private final MemoryManager memoryManager;
    private final ContextMerger merger;

    private static final Pattern CHINESE_PATTERN = Pattern.compile("[\\u4e00-\\u9fff]{2,}");

    public ContextBuilder(ContextSelector selector, ContextRouter router,
                          IdentityCollector identity, ConversationCollector conversation,
                          EnvironmentCollector environment,
                          MemoryManager memoryManager, ContextMerger merger) {
        this.selector = selector;
        this.router = router;
        this.planner = new RetrievalPlanner();
        this.identity = identity;
        this.conversation = conversation;
        this.environment = environment;
        this.memoryManager = memoryManager;
        this.merger = merger;
        log.info("ContextBuilder initialized with RetrievalPlanner and MemoryManager");
    }

    /**
     * Build context without a policy directive (uses defaults).
     * Delegates to {@link #build(TaskSpec, ContextPolicy.RetrievalDirective)} with null directive.
     */
    public CompletableFuture<UnifiedContext> build(TaskSpec task) {
        return build(task, null);
    }

    /**
     * Build unified context with policy-aware filtering.
     * <p>
     * The {@code directive} is applied to filter facts and memories by relevance score,
     * skip knowledge/tools when configured, and prevent injection of irrelevant personal
     * data (L1 intent-level filtering).
     *
     * @param task      the parsed task specification
     * @param directive policy directive from {@link ContextPolicy#evaluate(TaskSpec)},
     *                  may be null (falls back to defaults)
     */
    public CompletableFuture<UnifiedContext> build(TaskSpec task, ContextPolicy.RetrievalDirective directive) {
        try {
            var flags = selector.select(task);
            var routes = router.route(task, flags);
            var ctx = new UnifiedContext();

            // Plan retrieval strategy based on task intent
            var plan = planner.plan(task);
            log.info("Retrieval plan for {}: {}", task.getIntent().getValue(), plan);

            double minRelevanceScore = (directive != null) ? directive.getMinRelevanceScore() : 0.0;
            boolean skipKnowledge = directive != null && directive.isSkipKnowledge();
            boolean skipTools = directive != null && directive.isSkipTools();

            Map<ContextFlag, Object> collectorMap = Map.of(
                    ContextFlag.IDENTITY, identity,
                    ContextFlag.CONVERSATION, conversation,
                    ContextFlag.ENVIRONMENT, environment);

            var activeRoutes = routes.stream()
                    .filter(r -> collectorMap.containsKey(r.getFlag()))
                    .toList();

            // ── 1. Start collector tasks (parallel) ──
            var collectorFutures = activeRoutes.stream()
                    .<CompletableFuture<?>>map(r -> {
                        var c = collectorMap.get(r.getFlag());
                        if (c instanceof IdentityCollector ic) return ic.collect().thenApply(v -> (Object) v);
                        else if (c instanceof ConversationCollector cc) return cc.collect().thenApply(v -> (Object) v);
                        else if (c instanceof EnvironmentCollector ec) return ec.collect().thenApply(v -> (Object) v);
                        return CompletableFuture.completedFuture(null);
                    })
                    .toList();

            // ── 2. Multi-source retrieval via LongTermIndex ──
            // 2a. LongTermIndex (LTM + Episodic + Semantic global vector search)
            CompletableFuture<List<MemoryItem>> indexFuture = flags.contains(ContextFlag.MEMORY)
                    ? memoryManager.getIndex().query(task.getRawInput(), plan.getMemoryTopK())
                    .thenApply(LongTermIndex.IndexResult::items)
                    : CompletableFuture.completedFuture(List.of());

            // 2b. Conversation Memory (session history)
            CompletableFuture<List<MemoryItem>> convFuture = flags.contains(ContextFlag.CONVERSATION)
                    ? memoryManager.getConversation().retrieve(task.getRawInput(), plan.getConversationTopK())
                    : CompletableFuture.completedFuture(List.of());

            // 2g. Fact Memory — structured user facts (now intent-aware via FactMemory.retrieve)
            CompletableFuture<List<FactRecord>> factFuture = memoryManager.getFact()
                    .retrieve(task.getRawInput(), plan.getMemoryTopK());

            // ── 3. Merge all async results ──
            var allFutures = new ArrayList<CompletableFuture<?>>();
            allFutures.addAll(collectorFutures);
            allFutures.add(indexFuture);
            allFutures.add(convFuture);
            allFutures.add(factFuture);

            return CompletableFuture.allOf(allFutures.toArray(new CompletableFuture<?>[0]))
                    .thenApply(ignored -> {
                        // Process collector results
                        for (int i = 0; i < activeRoutes.size() && i < collectorFutures.size(); i++) {
                            try {
                                var result = collectorFutures.get(i).get();
                                if (result instanceof Exception e) {
                                    log.warn("Collector {} failed: {}", activeRoutes.get(i).getSource(), e.getMessage());
                                    continue;
                                }
                                var flag = activeRoutes.get(i).getFlag();
                                if (flag == ContextFlag.IDENTITY && result instanceof UserProfile up)
                                    ctx.setIdentity(up);
                                else if (flag == ContextFlag.CONVERSATION && result instanceof ConversationContext cc)
                                    ctx.setConversation(cc);
                                else if (flag == ContextFlag.ENVIRONMENT && result instanceof EnvironmentContext ec)
                                    ctx.setEnvironment(ec);
                            } catch (Exception e) {
                                log.warn("Failed to process collector result: {}", e.getMessage());
                            }
                        }

                        // ── Fusion: index results + conversation + facts ──
                        var allMemory = new ArrayList<MemoryItem>();
                        try {
                            var idxItems = indexFuture.get();
                            if (!skipKnowledge) {
                                allMemory.addAll(idxItems);
                            } else {
                                log.debug("Skipping knowledge index items (policy: skipKnowledge)");
                            }
                        } catch (Exception e) { log.warn("Index retrieve failed", e); }
                        try {
                            var convItems = convFuture.get();
                            convItems.forEach(i -> i.setRelevanceScore(i.getRelevanceScore() * 0.7));
                            allMemory.addAll(convItems);
                        } catch (Exception e) { log.warn("Conv retrieve failed", e); }
                        try {
                            var factItems = factFuture.get();
                            for (var f : factItems) {
                                // Dynamic relevance: combine confidence with keyword overlap.
                                // Previously hardcoded to 0.95 — now uses the fact's actual
                                // relevance to the current task query.
                                double relevance = computeFactRelevance(task.getRawInput(), f);
                                var item = new MemoryItem(MemoryType.FACT, String.format(
                                        "[Fact] %s = %s (%.2f)", f.getType(), f.getCurrentValue(), f.getConfidence()));
                                item.setRelevanceScore(relevance);
                                item.setMetadata(java.util.Map.of(
                                        "fact_type", f.getType(),
                                        "current_value", f.getCurrentValue(),
                                        "confidence", f.getConfidence()
                                ));
                                allMemory.add(item);
                            }
                        } catch (Exception e) { log.warn("Fact retrieve failed", e); }

                        // L1 + L2: Intent-aware relevance filtering
                        // Remove items below the policy's minimum relevance threshold
                        if (minRelevanceScore > 0) {
                            int before = allMemory.size();
                            allMemory.removeIf(item -> item.getRelevanceScore() < minRelevanceScore);
                            int removed = before - allMemory.size();
                            if (removed > 0) {
                                log.info("Policy filter (minRelevance={}): removed {} low-relevance items",
                                        minRelevanceScore, removed);
                            }
                        }

                        // Relevance Ranking
                        allMemory.sort((a, b) -> Double.compare(b.getRelevanceScore(), a.getRelevanceScore()));
                        ctx.setMemory(allMemory);
                        ctx.setKnowledge(new ArrayList<>());

                        // Normalize + Deduplicate
                        merger.normalize(ctx);
                        merger.deduplicate(ctx);

                        log.info("Context built: memory(total={}, index={}, conv={}, fact={}, minScore={})",
                                allMemory.size(),
                                safeIndexSize(indexFuture), safeSize(convFuture),
                                safeFSize(factFuture), minRelevanceScore);
                        return ctx;
                    });

        } catch (Exception e) {
            return CompletableFuture.failedFuture(
                    new ContextBuildException("Failed to build context: " + e.getMessage(), e));
        }
    }

    /**
     * Compute fact-to-task relevance based on how well the fact's type and value
     * match the user's raw input. Returns a value in [0, 1].
     */
    private double computeFactRelevance(String rawInput, FactRecord fact) {
        if (rawInput == null || rawInput.isBlank()) return fact.getConfidence() * 0.5;
        String q = rawInput.toLowerCase();
        String factText = (fact.getType() + " " + fact.getCurrentValue()).toLowerCase();
        String[] tokens = q.trim().split("\\s+");
        if (tokens.length == 0) return fact.getConfidence() * 0.5;
        long matchCount = java.util.Arrays.stream(tokens)
                .filter(t -> t.length() >= 2 && factText.contains(t))
                .count();
        double keywordScore = (double) matchCount / tokens.length;
        // Blend: keyword overlap (60%) + stored confidence (40%)
        return Math.min(1.0, keywordScore * 0.6 + fact.getConfidence() * 0.4);
    }

    private CompletableFuture<List<KnowledgeChunk>> retrieveSemanticKnowledge(TaskSpec task, int topK) {
        var conceptNames = new ArrayList<String>();
        for (var entity : task.getEntities()) {
            var value = entity.getValue();
            if (value != null && value.length() >= 2) conceptNames.add(value);
        }
        if (task.getRawInput() != null) {
            var matcher = CHINESE_PATTERN.matcher(task.getRawInput());
            while (matcher.find()) conceptNames.add(matcher.group());
        }

        var distinctNames = conceptNames.stream()
                .distinct()
                .limit(topK)
                .collect(Collectors.toList());
        if (distinctNames.isEmpty()) return CompletableFuture.completedFuture(List.of());

        var graphFutures = distinctNames.stream()
                .map(name -> memoryManager.getSemantic().queryGraph(name, 1))
                .toList();

        return CompletableFuture.allOf(graphFutures.toArray(new CompletableFuture<?>[0]))
                .thenApply(v -> {
                    var knowledge = new ArrayList<KnowledgeChunk>();
                    for (int i = 0; i < graphFutures.size() && i < distinctNames.size(); i++) {
                        try {
                            var graph = graphFutures.get(i).get();
                            var nodes = (List<?>) graph.getOrDefault("nodes", List.of());
                            var edges = (List<?>) graph.getOrDefault("edges", List.of());
                            if (!nodes.isEmpty() || !edges.isEmpty()) {
                                var content = new StringBuilder("Knowledge graph for \"" + distinctNames.get(i) + "\":\n");
                                for (var n : nodes) {
                                    if (n instanceof Map<?, ?> nm)
                                        content.append("- Concept: ").append(nm.get("name")).append("\n");
                                }
                                for (var e : edges) {
                                    if (e instanceof Map<?, ?> em)
                                        content.append("- Relation: ").append(em.get("source"))
                                                .append(" --[").append(em.get("type")).append("]--> ")
                                                .append(em.get("target")).append("\n");
                                }
                                knowledge.add(new KnowledgeChunk("semantic_memory", content.toString()));
                            }
                        } catch (Exception e) {
                            log.debug("Semantic query failed for '{}'", distinctNames.get(i), e);
                        }
                    }
                    return knowledge;
                });
    }

    private static int safeSize(CompletableFuture<List<MemoryItem>> f) {
        try { return f.get().size(); } catch (Exception e) { return -1; }
    }
    private static int safeKSize(CompletableFuture<List<KnowledgeChunk>> f) {
        try { return f.get().size(); } catch (Exception e) { return -1; }
    }
    private static int safeFSize(CompletableFuture<List<FactRecord>> f) {
        try { return f.get().size(); } catch (Exception e) { return -1; }
    }
    private static int safeIndexSize(CompletableFuture<List<MemoryItem>> f) {
        try { return f.get().size(); } catch (Exception e) { return -1; }
    }
}
