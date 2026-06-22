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

    public CompletableFuture<UnifiedContext> build(TaskSpec task) {
        try {
            var flags = selector.select(task);
            var routes = router.route(task, flags);
            var ctx = new UnifiedContext();

            // Plan retrieval strategy based on task intent
            var plan = planner.plan(task);
            log.info("Retrieval plan for {}: {}", task.getIntent().getValue(), plan);

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

            // ── 2. Start multi-source retrieval (parallel) ──
            // 2a. Long-term Memory
            CompletableFuture<List<MemoryItem>> ltmFuture = flags.contains(ContextFlag.MEMORY)
                    ? memoryManager.getLongTerm().retrieve(task.getRawInput(), plan.getMemoryTopK(), null, null)
                    : CompletableFuture.completedFuture(List.of());

            // 2b. Conversation Memory (session history)
            CompletableFuture<List<MemoryItem>> convFuture = flags.contains(ContextFlag.CONVERSATION)
                    ? memoryManager.getConversation().retrieve(task.getRawInput(), plan.getConversationTopK())
                    : CompletableFuture.completedFuture(List.of());

            // 2c. Episodic Memory — similar past experiences
            CompletableFuture<List<MemoryItem>> epFuture = flags.contains(ContextFlag.MEMORY)
                    ? memoryManager.getEpisodic().recallSimilar(task.getRawInput(), plan.getEpisodeTopK())
                    : CompletableFuture.completedFuture(List.of());

            // 2d. Reflection Memory — past lessons
            CompletableFuture<List<MemoryItem>> refFuture = flags.contains(ContextFlag.MEMORY)
                    ? memoryManager.getReflection().retrieve(task.getRawInput(), plan.getReflectionTopK())
                    : CompletableFuture.completedFuture(List.of());

            // 2e. Semantic Memory — knowledge graph queries
            CompletableFuture<List<KnowledgeChunk>> semFuture = flags.contains(ContextFlag.KNOWLEDGE)
                    ? retrieveSemanticKnowledge(task, plan.getKnowledgeTopK())
                    : CompletableFuture.completedFuture(List.of());

            // 2f. Procedural Memory — learned procedures
            CompletableFuture<List<MemoryItem>> procFuture = flags.contains(ContextFlag.MEMORY)
                    ? memoryManager.getProcedural().retrieve(task.getRawInput(), task.getDomain(), plan.getToolTopK())
                    : CompletableFuture.completedFuture(List.of());

            // 2g. Fact Memory — structured user facts (always retrieved for personalization)
            CompletableFuture<List<FactRecord>> factFuture = memoryManager.getFact()
                    .retrieve(task.getRawInput(), plan.getMemoryTopK());

            // ── 3. Merge all async results ──
            var allFutures = new ArrayList<CompletableFuture<?>>();
            allFutures.addAll(collectorFutures);
            allFutures.add(ltmFuture);
            allFutures.add(convFuture);
            allFutures.add(epFuture);
            allFutures.add(refFuture);
            allFutures.add(semFuture);
            allFutures.add(procFuture);
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

                        // ── Fusion: merge all memory sources ──
                        var allMemory = new ArrayList<MemoryItem>();
                        try {
                            var ltmItems = ltmFuture.get();
                            ltmItems.forEach(i -> i.setRelevanceScore(i.getRelevanceScore() * 0.9));
                            allMemory.addAll(ltmItems);
                        } catch (Exception e) { log.warn("LTM retrieve failed", e); }
                        try {
                            var convItems = convFuture.get();
                            convItems.forEach(i -> i.setRelevanceScore(i.getRelevanceScore() * 0.7));
                            allMemory.addAll(convItems);
                        } catch (Exception e) { log.warn("Conv retrieve failed", e); }
                        try {
                            var epItems = epFuture.get();
                            epItems.forEach(i -> i.setRelevanceScore(i.getRelevanceScore() * 0.8));
                            allMemory.addAll(epItems);
                        } catch (Exception e) { log.warn("Episodic retrieve failed", e); }
                        try {
                            var refItems = refFuture.get();
                            refItems.forEach(i -> i.setRelevanceScore(i.getRelevanceScore() * 0.85));
                            allMemory.addAll(refItems);
                        } catch (Exception e) { log.warn("Reflection retrieve failed", e); }
                        try {
                            var procItems = procFuture.get();
                            procItems.forEach(i -> i.setRelevanceScore(i.getRelevanceScore() * 0.75));
                            allMemory.addAll(procItems);
                        } catch (Exception e) { log.warn("Procedural retrieve failed", e); }
                        try {
                            var factItems = factFuture.get();
                            for (var f : factItems) {
                                var item = new MemoryItem(MemoryType.FACT, String.format(
                                        "[Fact] %s = %s (%.2f)", f.getType(), f.getCurrentValue(), f.getConfidence()));
                                item.setRelevanceScore(0.95); // facts are highly relevant
                                item.setMetadata(java.util.Map.of(
                                        "fact_type", f.getType(),
                                        "current_value", f.getCurrentValue(),
                                        "confidence", f.getConfidence()
                                ));
                                allMemory.add(item);
                            }
                        } catch (Exception e) { log.warn("Fact retrieve failed", e); }

                        // Relevance Ranking
                        allMemory.sort((a, b) -> Double.compare(b.getRelevanceScore(), a.getRelevanceScore()));
                        ctx.setMemory(allMemory);

                        // Knowledge
                        try { ctx.setKnowledge(semFuture.get()); } catch (Exception e) {
                            log.warn("Semantic retrieve failed", e);
                        }

                        // Normalize + Deduplicate
                        merger.normalize(ctx);
                        merger.deduplicate(ctx);

                        log.info("Context built: memory(total={}, ltm={}, conv={}, ep={}, ref={}, proc={}, fact={}), knowledge={}",
                                allMemory.size(),
                                safeSize(ltmFuture), safeSize(convFuture), safeSize(epFuture),
                                safeSize(refFuture), safeSize(procFuture), safeFSize(factFuture),
                                safeKSize(semFuture));
                        return ctx;
                    });

        } catch (Exception e) {
            return CompletableFuture.failedFuture(
                    new ContextBuildException("Failed to build context: " + e.getMessage(), e));
        }
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
}
