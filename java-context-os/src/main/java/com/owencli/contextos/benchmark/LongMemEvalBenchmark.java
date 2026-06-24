package com.owencli.contextos.benchmark;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.model.LLMProvider;
import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.UnifiedContext;
import com.owencli.contextos.feedback.MemoryUpdateResult;
import com.owencli.contextos.llm.DeepSeekClient;
import com.owencli.contextos.llm.OpenAIClient;
import com.owencli.contextos.pipeline.ContextOSPipeline;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.io.FileWriter;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;

/**
 * LongMemEval Benchmark — evaluates Context-OS on the LongMemEval dataset.
 * <p>
 * Dataset: https://huggingface.co/datasets/xiaowu0162/longmemeval
 * Paper: LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory (ICLR 2025)
 * <p>
 * Usage:
 * java com.owencli.contextos.benchmark.LongMemEvalBenchmark --data data/longmemeval/longmemeval_oracle --max-eval 20
 */
public class LongMemEvalBenchmark {

    private static final Logger log = LoggerFactory.getLogger(LongMemEvalBenchmark.class);
    private static final ObjectMapper MAPPER = new ObjectMapper()
            .enable(SerializationFeature.INDENT_OUTPUT);
    private static final Set<String> STOP_WORDS = Set.of(
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "to", "of", "in", "on", "at", "for", "and", "or", "but",
            "this", "that", "it", "as", "by", "with", "from", "not",
            "he", "she", "they", "we", "you", "i", "his", "her", "their");

    // ═══════════════════════════════════════════════════════
    // SimpleAgent — no memory, just concatenates history
    // ═══════════════════════════════════════════════════════

    static class SimpleAgent {
        private final BaseLLMClient llmClient;
        private final int maxHistoryTurns;
        private final List<Map<String, String>> history = new ArrayList<>();

        SimpleAgent(BaseLLMClient llmClient, int maxHistoryTurns) {
            this.llmClient = llmClient;
            this.maxHistoryTurns = maxHistoryTurns;
        }

        CompletableFuture<Void> ingestSession(List<Map<String, String>> turns) {
            history.addAll(turns);
            return CompletableFuture.completedFuture(null);
        }

        CompletableFuture<String> answer(String question) {
            int start = Math.max(0, history.size() - maxHistoryTurns);
            var recent = history.subList(start, history.size());
            var ctxLines = recent.stream()
                    .map(t -> t.get("role") + ": " + t.get("content"))
                    .collect(Collectors.joining("\n"));
            var prompt = "You are a helpful assistant. Based on the conversation history below, " +
                    "answer the user's question concisely.\n\n" +
                    "Conversation history:\n" + ctxLines +
                    "\n\nQuestion: " + question + "\nAnswer:";
            return llmClient.complete(prompt, 500)
                    .thenApply(r -> r.toString().trim());
        }

        void reset() { history.clear(); }
    }

    // ═══════════════════════════════════════════════════════
    // AnswerDetail — enriched answer with memory context
    // ═══════════════════════════════════════════════════════

    static class AnswerDetail {
        final String response;
        final List<MemoryItem> retrievedMemories;
        AnswerDetail(String response, List<MemoryItem> retrievedMemories) {
            this.response = response;
            this.retrievedMemories = retrievedMemories;
        }
    }

    // ═══════════════════════════════════════════════════════
    // MemoryMetrics — per-instance memory performance metrics
    // ═══════════════════════════════════════════════════════

    static class MemoryMetrics {
        // Write accuracy
        int totalSteps = 0;
        int totalFactsSaved = 0;
        int ltmWrites = 0;
        int episodicWrites = 0;
        int semanticWrites = 0;
        double totalImportanceScore = 0.0;
        int conflictCount = 0;

        // Retrieval
        double retrievalRecall = 0.0;          // answer keywords found in retrieved memories
        int retrievedCount = 0;                // number of MemoryItems retrieved during answer
        boolean retrievalHit = false;          // at least one retrieved memory matched answer

        void recordIngest(MemoryUpdateResult r) {
            if (r == null) return;
            totalSteps++;
            totalFactsSaved += r.getFactsSaved();
            totalImportanceScore += r.getFinalScore();
            if (r.isSavedToLTM()) ltmWrites++;
            if (r.isSavedToEpisodic()) episodicWrites++;
            if (r.isSavedToSemantic()) semanticWrites++;
            if (r.isHasConflict()) conflictCount++;
        }

        void recordRetrieval(List<MemoryItem> memories, String answer) {
            if (memories == null) memories = List.of();
            retrievedCount = memories.size();

            if (answer == null || answer.isEmpty() || memories.isEmpty()) {
                retrievalRecall = 0.0;
                retrievalHit = false;
                return;
            }

            String ansNorm = normalizeText(answer);
            var ansTokens = Arrays.stream(ansNorm.split("\\s+"))
                    .filter(t -> !STOP_WORDS.contains(t) && t.length() > 1)
                    .collect(Collectors.toList());

            if (ansTokens.isEmpty()) {
                retrievalRecall = 1.0;
                retrievalHit = true;
                return;
            }

            // Check each memory item individually for hit; concatenate all for recall
            for (var mem : memories) {
                String memNorm = normalizeText(mem.getContent() != null ? mem.getContent() : "");
                long hits = ansTokens.stream().filter(memNorm::contains).count();
                if ((double) hits / ansTokens.size() >= 0.3) {
                    retrievalHit = true;
                    break;
                }
            }

            String allContent = memories.stream()
                    .map(m -> normalizeText(m.getContent() != null ? m.getContent() : ""))
                    .collect(Collectors.joining(" "));

            long hits = ansTokens.stream().filter(allContent::contains).count();
            retrievalRecall = (double) hits / ansTokens.size();
        }

        double getAvgImportance() { return totalSteps > 0 ? totalImportanceScore / totalSteps : 0; }
        double getFactsPerStep()  { return totalSteps > 0 ? (double) totalFactsSaved / totalSteps : 0; }
        double getLtmWriteRate()  { return totalSteps > 0 ? (double) ltmWrites / totalSteps : 0; }
        double getEpiWriteRate()  { return totalSteps > 0 ? (double) episodicWrites / totalSteps : 0; }
        double getSemWriteRate()  { return totalSteps > 0 ? (double) semanticWrites / totalSteps : 0; }

        Map<String, Object> toMap() {
            var m = new LinkedHashMap<String, Object>();
            m.put("total_steps", totalSteps);
            m.put("total_facts_saved", totalFactsSaved);
            m.put("avg_facts_per_step", Math.round(getFactsPerStep() * 1000.0) / 1000.0);
            m.put("ltm_write_rate", Math.round(getLtmWriteRate() * 1000.0) / 1000.0);
            m.put("episodic_write_rate", Math.round(getEpiWriteRate() * 1000.0) / 1000.0);
            m.put("semantic_write_rate", Math.round(getSemWriteRate() * 1000.0) / 1000.0);
            m.put("avg_importance_score", Math.round(getAvgImportance() * 1000.0) / 1000.0);
            m.put("conflict_count", conflictCount);
            m.put("retrieval_recall", Math.round(retrievalRecall * 1000.0) / 1000.0);
            m.put("retrieved_count", retrievedCount);
            m.put("retrieval_hit", retrievalHit);
            return m;
        }
    }

    // ═══════════════════════════════════════════════════════
    // MemoryAgent — full Context-OS pipeline (instrumented)
    // ═══════════════════════════════════════════════════════

    static class MemoryAgent {
        private final ContextOSPipeline pipeline;
        private boolean initialized = false;
        private final List<MemoryUpdateResult> ingestMetrics = new ArrayList<>();

        MemoryAgent(BaseLLMClient llmClient, String dbPath) {
            String providerName = llmClient.getClass().getSimpleName().toLowerCase();
            LLMProvider provider;
            if (providerName.contains("anthropic")) provider = LLMProvider.CLAUDE;
            else if (providerName.contains("openai")) provider = LLMProvider.OPENAI;
            else provider = LLMProvider.DEEPSEEK;

            String ts = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"));
            this.pipeline = new ContextOSPipeline(
                    llmClient, provider, dbPath,
                    "lme-" + ts, "lme-test");
        }

        CompletableFuture<Void> ensure() {
            if (!initialized) {
                return pipeline.ensureStore().thenRun(() -> initialized = true);
            }
            return CompletableFuture.completedFuture(null);
        }

        /** Reset ingest metrics for a new evaluation instance. */
        void resetMetrics() {
            ingestMetrics.clear();
        }

        /** Ingest session turns and collect MemoryUpdateResult for write accuracy metrics. */
        CompletableFuture<Void> ingestSession(List<Map<String, String>> turns) {
            return ensure().thenCompose(v -> {
                var futures = turns.stream()
                        .filter(t -> "user".equals(t.get("role")))
                        .map(t -> pipeline.run(t.get("content"))
                                .thenAccept(result -> {
                                    if (result != null && result.get("memory_update") instanceof MemoryUpdateResult mr) {
                                        synchronized (ingestMetrics) {
                                            ingestMetrics.add(mr);
                                        }
                                    }
                                })
                                .exceptionally(e -> {
                                    log.warn("Ingest failed: {}", e.getMessage());
                                    return null;
                                }))
                        .toArray(CompletableFuture[]::new);
                return CompletableFuture.allOf(futures);
            });
        }

        /** Answer a question AND capture the retrieved memory context. */
        CompletableFuture<AnswerDetail> answerWithDetail(String question) {
            return ensure().thenCompose(v ->
                    pipeline.run(question).thenApply(result -> {
                        String response = (String) result.get("response");
                        response = response != null ? response.trim() : "";

                        List<MemoryItem> memories = List.of();
                        if (result.get("unified_context") instanceof UnifiedContext ctx) {
                            memories = ctx.getMemory();
                        }
                        return new AnswerDetail(response, memories);
                    }).exceptionally(e ->
                            new AnswerDetail("[ERROR] " + e.getMessage(), List.of())));
        }

        /** Build aggregate MemoryMetrics for this evaluation instance. */
        MemoryMetrics computeMetrics(String answer) {
            var mm = new MemoryMetrics();
            for (var mr : ingestMetrics) {
                mm.recordIngest(mr);
            }
            return mm;
        }

        CompletableFuture<Void> close() {
            return pipeline.close();
        }
    }

    // ═══════════════════════════════════════════════════════
    // Metrics
    // ═══════════════════════════════════════════════════════

    static String normalizeText(String s) {
        if (s == null) return "";
        return s.toLowerCase().strip()
                .replaceAll("[^\\w\\s]", " ")
                .replaceAll("\\s+", " ")
                .trim();
    }

    static double keywordOverlapScore(String hypothesis, String answer) {
        String hypNorm = normalizeText(hypothesis);
        String ansNorm = normalizeText(answer);

        var ansTokens = Arrays.stream(ansNorm.split("\\s+"))
                .filter(t -> !STOP_WORDS.contains(t) && t.length() > 1)
                .collect(Collectors.toList());

        if (ansTokens.isEmpty()) return hypNorm.isEmpty() ? 1.0 : 0.0;

        long hits = ansTokens.stream().filter(hypNorm::contains).count();
        return (double) hits / ansTokens.size();
    }

    static boolean isCorrect(String hypothesis, String answer, double threshold) {
        return keywordOverlapScore(hypothesis, answer) >= threshold;
    }

    // ═══════════════════════════════════════════════════════
    // Main benchmark runner
    // ═══════════════════════════════════════════════════════

    public static void runBenchmark(String dataPath, BaseLLMClient llmClient,
                                    String dbPath, int maxEval, String outputDir,
                                    boolean skipSimple) throws Exception {
        // Load data
        System.out.println("Loading data from: " + dataPath);
        var dataFile = new File(dataPath);
        List<Map<String, Object>> data = MAPPER.readValue(dataFile, new TypeReference<>() {});

        if (maxEval > 0 && maxEval < data.size()) {
            data = data.subList(0, maxEval);
        }
        System.out.println("Evaluating " + data.size() + " instances");

        // Initialize agents
        var memoryAgent = new MemoryAgent(llmClient, dbPath);
        var simpleAgent = skipSimple ? null : new SimpleAgent(llmClient, 10);

        // Stats grouped by question_type
        var resultsByType = new LinkedHashMap<String, Map<String, Object>>();
        var allResults = new ArrayList<Map<String, Object>>();
        long tStart = System.currentTimeMillis();

        // Memory metrics accumulators (per question_type)
        // We store arrays so we can atomically update them in the loop
        var memTotalSteps = new LinkedHashMap<String, double[]>();       // [sum]
        var memTotalFacts = new LinkedHashMap<String, double[]>();      // [sum]
        var memLtmWrites = new LinkedHashMap<String, double[]>();       // [sum]
        var memEpiWrites = new LinkedHashMap<String, double[]>();       // [sum]
        var memSemWrites = new LinkedHashMap<String, double[]>();       // [sum]
        var memRecall    = new LinkedHashMap<String, double[]>();       // [sum]
        var memHitCount  = new LinkedHashMap<String, double[]>();       // [sum]
        var memAvgImport = new LinkedHashMap<String, double[]>();       // [sum]

        for (int idx = 0; idx < data.size(); idx++) {
            var inst = data.get(idx);
            String qid = (String) inst.get("question_id");
            String qtype = (String) inst.get("question_type");
            String question = (String) inst.get("question");
            String answer = (String) inst.get("answer");

            @SuppressWarnings("unchecked")
            var sessions = (List<List<Map<String, String>>>) inst.get("haystack_sessions");

            System.out.printf("\r[%d/%d] %-30s (%d sessions)...",
                    idx + 1, data.size(), qtype, sessions.size());

            // ═══════════════════════════════════════
            // Agent B: MemoryAgent (with instrumented metrics)
            // ═══════════════════════════════════════
            memoryAgent.pipeline.getConversationCollector().clear();
            memoryAgent.resetMetrics();

            // Ingest: automatically collects MemoryUpdateResult
            for (var session : sessions) {
                memoryAgent.ingestSession(session).join();
            }

            // Answer: captures retrieved memories from UnifiedContext
            var answerDetail = memoryAgent.answerWithDetail(question).join();
            String respB = answerDetail.response;
            double scoreB = keywordOverlapScore(respB, answer);
            boolean correctB = isCorrect(respB, answer, 0.5);

            // Compute memory metrics for this instance
            var memMetrics = memoryAgent.computeMetrics(answer);
            memMetrics.recordRetrieval(answerDetail.retrievedMemories, answer);

            // ═══════════════════════════════════════
            // Agent A: SimpleAgent (baseline)
            // ═══════════════════════════════════════
            double scoreA = 0.0;
            boolean correctA = false;
            String respA = "";
            if (simpleAgent != null) {
                simpleAgent.reset();
                for (var session : sessions) {
                    simpleAgent.ingestSession(session).join();
                }
                respA = simpleAgent.answer(question).join();
                scoreA = keywordOverlapScore(respA, answer);
                correctA = isCorrect(respA, answer, 0.5);
            }

            // ═══════════════════════════════════════
            // Aggregate stats by question_type
            // ═══════════════════════════════════════
            var stats = resultsByType.computeIfAbsent(qtype, k -> {
                var m = new LinkedHashMap<String, Object>();
                m.put("total", new AtomicInteger(0));
                m.put("correct_a", new AtomicInteger(0));
                m.put("correct_b", new AtomicInteger(0));
                m.put("score_a", new double[]{0.0});
                m.put("score_b", new double[]{0.0});
                return m;
            });
            ((AtomicInteger) stats.get("total")).incrementAndGet();
            ((AtomicInteger) stats.get("correct_a")).addAndGet(correctA ? 1 : 0);
            ((AtomicInteger) stats.get("correct_b")).addAndGet(correctB ? 1 : 0);
            ((double[]) stats.get("score_a"))[0] += scoreA;
            ((double[]) stats.get("score_b"))[0] += scoreB;

            // Aggregate memory metrics
            memTotalSteps.computeIfAbsent(qtype, k -> new double[1])[0] += memMetrics.totalSteps;
            memTotalFacts.computeIfAbsent(qtype, k -> new double[1])[0] += memMetrics.totalFactsSaved;
            memLtmWrites.computeIfAbsent(qtype, k -> new double[1])[0] += memMetrics.ltmWrites;
            memEpiWrites.computeIfAbsent(qtype, k -> new double[1])[0] += memMetrics.episodicWrites;
            memSemWrites.computeIfAbsent(qtype, k -> new double[1])[0] += memMetrics.semanticWrites;
            memRecall.computeIfAbsent(qtype, k -> new double[1])[0] += memMetrics.retrievalRecall;
            memHitCount.computeIfAbsent(qtype, k -> new double[1])[0] += memMetrics.retrievalHit ? 1 : 0;
            memAvgImport.computeIfAbsent(qtype, k -> new double[1])[0] += memMetrics.getAvgImportance();

            // Add memory metrics to per-instance detail
            var detail = new LinkedHashMap<String, Object>();
            detail.put("question_id", qid);
            detail.put("question_type", qtype);
            detail.put("question", truncate(question, 100));
            detail.put("answer", truncate(answer, 100));
            detail.put("hypothesis_simple", truncate(respA, 200));
            detail.put("hypothesis_memory", truncate(respB, 200));
            detail.put("score_a", Math.round(scoreA * 1000.0) / 1000.0);
            detail.put("score_b", Math.round(scoreB * 1000.0) / 1000.0);
            detail.put("correct_a", correctA);
            detail.put("correct_b", correctB);
            detail.put("memory_metrics", memMetrics.toMap());
            allResults.add(detail);
        }

        double elapsed = (System.currentTimeMillis() - tStart) / 1000.0;
        memoryAgent.close().join();

        // ── Report ──
        System.out.println("\n");
        System.out.println("=" .repeat(90));
        System.out.println("  LongMemEval 基准测试报告");
        System.out.println("=" .repeat(90));
        System.out.printf("  数据集:    %s%n", dataFile.getName());
        System.out.printf("  实例数:    %d%n", data.size());
        System.out.printf("  LLM:       %s%n", llmClient.getClass().getSimpleName());
        System.out.printf("  耗时:      %.1f 分钟%n", elapsed / 60);
        System.out.println("-" .repeat(90));
        System.out.printf("  %-32s %4s %14s %14s %10s %10s%n",
                "类型", "数量", "Simple准确率", "Memory准确率", "Simple F1", "Memory F1");
        System.out.println("-" .repeat(90));

        int totalA = 0, totalB = 0, totalCount = 0;
        double totalScoreA = 0, totalScoreB = 0;

        for (var entry : resultsByType.entrySet()) {
            var s = entry.getValue();
            int n = ((AtomicInteger) s.get("total")).get();
            int cA = ((AtomicInteger) s.get("correct_a")).get();
            int cB = ((AtomicInteger) s.get("correct_b")).get();
            double sA = ((double[]) s.get("score_a"))[0];
            double sB = ((double[]) s.get("score_b"))[0];

            double accA = n > 0 ? (double) cA / n : 0;
            double accB = n > 0 ? (double) cB / n : 0;
            double avgA = n > 0 ? sA / n : 0;
            double avgB = n > 0 ? sB / n : 0;

            System.out.printf("  %-32s %4d %13.1f%% %13.1f%% %10.3f %10.3f%n",
                    entry.getKey(), n, accA * 100, accB * 100, avgA, avgB);

            totalA += cA;
            totalB += cB;
            totalScoreA += sA;
            totalScoreB += sB;
            totalCount += n;
        }

        System.out.println("-" .repeat(90));
        System.out.printf("  %-32s %4d %13.1f%% %13.1f%% %10.3f %10.3f%n",
                "TOTAL", totalCount,
                (double) totalA / totalCount * 100,
                (double) totalB / totalCount * 100,
                totalScoreA / totalCount,
                totalScoreB / totalCount);
        System.out.println("=" .repeat(90));

        double deltaAcc = totalCount > 0 ? (double) (totalB - totalA) / totalCount : 0;
        double deltaF1 = totalCount > 0 ? (totalScoreB - totalScoreA) / totalCount : 0;
        System.out.printf("  准确率提升: %+.1f%%%n", deltaAcc * 100);
        System.out.printf("  F1 提升:    %+.3f%n", deltaF1);
        System.out.println("=" .repeat(90));

        // ═══════════════════════════════════════════
        // Memory Metrics Report
        // ═══════════════════════════════════════════

        System.out.println("\n  记忆写入准确率 (Write Accuracy)");
        System.out.println("-" .repeat(90));
        System.out.printf("  %-30s %6s %7s %8s %8s %8s%n",
                "类型", "步骤", "LTM率", "Epi率", "Sem率", "事实/步");
        System.out.println("-" .repeat(90));

        int totalStepsAll = 0, totalFactsAll = 0, totalLtmAll = 0, totalEpiAll = 0, totalSemAll = 0;
        for (var entry : resultsByType.entrySet()) {
            String k = entry.getKey();
            int steps = (int) Math.round(memTotalSteps.getOrDefault(k, new double[1])[0]);
            int facts = (int) Math.round(memTotalFacts.getOrDefault(k, new double[1])[0]);
            int ltm   = (int) Math.round(memLtmWrites.getOrDefault(k, new double[1])[0]);
            int epi   = (int) Math.round(memEpiWrites.getOrDefault(k, new double[1])[0]);
            int sem   = (int) Math.round(memSemWrites.getOrDefault(k, new double[1])[0]);

            double ltmRate = steps > 0 ? (double) ltm / steps : 0;
            double epiRate = steps > 0 ? (double) epi / steps : 0;
            double semRate = steps > 0 ? (double) sem / steps : 0;
            double factsPerStep = steps > 0 ? (double) facts / steps : 0;

            System.out.printf("  %-30s %6d %6.1f%% %7.1f%% %7.1f%% %9.2f%n",
                    k, steps, ltmRate * 100, epiRate * 100, semRate * 100, factsPerStep);

            totalStepsAll += steps;
            totalFactsAll += facts;
            totalLtmAll += ltm;
            totalEpiAll += epi;
            totalSemAll += sem;
        }
        System.out.println("-" .repeat(90));
        double tLtmRate = totalStepsAll > 0 ? (double) totalLtmAll / totalStepsAll : 0;
        double tEpiRate = totalStepsAll > 0 ? (double) totalEpiAll / totalStepsAll : 0;
        double tSemRate = totalStepsAll > 0 ? (double) totalSemAll / totalStepsAll : 0;
        double tFactsPerStep = totalStepsAll > 0 ? (double) totalFactsAll / totalStepsAll : 0;
        System.out.printf("  %-30s %6d %6.1f%% %7.1f%% %7.1f%% %9.2f%n",
                "TOTAL", totalStepsAll, tLtmRate * 100, tEpiRate * 100, tSemRate * 100, tFactsPerStep);
        System.out.println("=" .repeat(90));

        System.out.println("\n  记忆检索召回率 (Retrieval Recall)");
        System.out.println("-" .repeat(90));
        System.out.printf("  %-30s %6s %10s %8s%n",
                "类型", "实例数", "召回率", "Hit@k");
        System.out.println("-" .repeat(90));

        double totalRecall = 0, totalHitCount = 0;
        for (var entry : resultsByType.entrySet()) {
            String k = entry.getKey();
            int n = ((AtomicInteger) entry.getValue().get("total")).get();
            double recall = memRecall.getOrDefault(k, new double[1])[0];
            double hits  = memHitCount.getOrDefault(k, new double[1])[0];

            double avgRecall = n > 0 ? recall / n : 0;
            double hitRate   = n > 0 ? hits / n : 0;

            System.out.printf("  %-30s %6d %9.1f%% %7.1f%%%n",
                    k, n, avgRecall * 100, hitRate * 100);

            totalRecall += recall;
            totalHitCount += hits;
        }
        System.out.println("-" .repeat(90));
        double avgRecallAll = totalCount > 0 ? totalRecall / totalCount : 0;
        double hitRateAll   = totalCount > 0 ? totalHitCount / totalCount : 0;
        System.out.printf("  %-30s %6d %9.1f%% %7.1f%%%n",
                "TOTAL", totalCount, avgRecallAll * 100, hitRateAll * 100);
        System.out.println("=" .repeat(90));

        // ── Save results ──
        Files.createDirectories(Paths.get(outputDir));
        String ts = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
        var summary = new LinkedHashMap<String, Object>();
        summary.put("dataset", dataFile.getName());
        summary.put("num_instances", totalCount);
        summary.put("duration_minutes", Math.round(elapsed / 6) / 10.0);
        summary.put("llm", llmClient.getClass().getSimpleName());

        var byType = new LinkedHashMap<String, Object>();
        var memByType = new LinkedHashMap<String, Object>();
        for (var entry : resultsByType.entrySet()) {
            String k = entry.getKey();
            var s = entry.getValue();
            int n = ((AtomicInteger) s.get("total")).get();
            int cA = ((AtomicInteger) s.get("correct_a")).get();
            int cB = ((AtomicInteger) s.get("correct_b")).get();
            double sA = ((double[]) s.get("score_a"))[0];
            double sB = ((double[]) s.get("score_b"))[0];

            var bt = new LinkedHashMap<String, Object>();
            bt.put("count", n);
            bt.put("acc_simple", Math.round((double) cA / n * 1000.0) / 1000.0);
            bt.put("acc_memory", Math.round((double) cB / n * 1000.0) / 1000.0);
            bt.put("f1_simple", Math.round(sA / n * 1000.0) / 1000.0);
            bt.put("f1_memory", Math.round(sB / n * 1000.0) / 1000.0);
            byType.put(k, bt);

            // Memory metrics per type
            int steps = (int) Math.round(memTotalSteps.getOrDefault(k, new double[1])[0]);
            int facts = (int) Math.round(memTotalFacts.getOrDefault(k, new double[1])[0]);
            int ltm   = (int) Math.round(memLtmWrites.getOrDefault(k, new double[1])[0]);
            int epi   = (int) Math.round(memEpiWrites.getOrDefault(k, new double[1])[0]);
            int sem   = (int) Math.round(memSemWrites.getOrDefault(k, new double[1])[0]);
            double recall = memRecall.getOrDefault(k, new double[1])[0];
            double hits  = memHitCount.getOrDefault(k, new double[1])[0];

            var mt = new LinkedHashMap<String, Object>();
            mt.put("count", n);
            mt.put("total_steps", steps);
            mt.put("total_facts_saved", facts);
            mt.put("ltm_write_rate", steps > 0 ? Math.round((double) ltm / steps * 1000.0) / 1000.0 : 0);
            mt.put("episodic_write_rate", steps > 0 ? Math.round((double) epi / steps * 1000.0) / 1000.0 : 0);
            mt.put("semantic_write_rate", steps > 0 ? Math.round((double) sem / steps * 1000.0) / 1000.0 : 0);
            mt.put("facts_per_step", steps > 0 ? Math.round((double) facts / steps * 1000.0) / 1000.0 : 0);
            mt.put("retrieval_recall", n > 0 ? Math.round(recall / n * 1000.0) / 1000.0 : 0);
            mt.put("retrieval_hit_rate", n > 0 ? Math.round(hits / n * 1000.0) / 1000.0 : 0);
            memByType.put(k, mt);
        }
        summary.put("by_type", byType);

        var overall = new LinkedHashMap<String, Object>();
        overall.put("acc_simple", Math.round((double) totalA / totalCount * 1000.0) / 1000.0);
        overall.put("acc_memory", Math.round((double) totalB / totalCount * 1000.0) / 1000.0);
        overall.put("f1_simple", Math.round(totalScoreA / totalCount * 1000.0) / 1000.0);
        overall.put("f1_memory", Math.round(totalScoreB / totalCount * 1000.0) / 1000.0);
        overall.put("delta_acc", Math.round(deltaAcc * 1000.0) / 1000.0);
        overall.put("delta_f1", Math.round(deltaF1 * 1000.0) / 1000.0);

        var memOverall = new LinkedHashMap<String, Object>();
        memOverall.put("ltm_write_rate", totalStepsAll > 0 ? Math.round((double) totalLtmAll / totalStepsAll * 1000.0) / 1000.0 : 0);
        memOverall.put("episodic_write_rate", totalStepsAll > 0 ? Math.round((double) totalEpiAll / totalStepsAll * 1000.0) / 1000.0 : 0);
        memOverall.put("semantic_write_rate", totalStepsAll > 0 ? Math.round((double) totalSemAll / totalStepsAll * 1000.0) / 1000.0 : 0);
        memOverall.put("avg_facts_per_step", totalStepsAll > 0 ? Math.round((double) totalFactsAll / totalStepsAll * 1000.0) / 1000.0 : 0);
        memOverall.put("retrieval_recall", totalCount > 0 ? Math.round(totalRecall / totalCount * 1000.0) / 1000.0 : 0);
        memOverall.put("retrieval_hit_rate", totalCount > 0 ? Math.round(totalHitCount / totalCount * 1000.0) / 1000.0 : 0);

        overall.put("memory_metrics", memOverall);
        summary.put("overall", overall);
        summary.put("memory_by_type", memByType);
        summary.put("details", allResults);

        String outFile = Paths.get(outputDir, "longmemeval_result_" + ts + ".json").toString();
        MAPPER.writeValue(new File(outFile), summary);
        System.out.println("\n详细结果已保存: " + outFile);

        // JSONL output
        String jsonlSimple = Paths.get(outputDir, "lme_simple_" + ts + ".jsonl").toString();
        String jsonlMemory = Paths.get(outputDir, "lme_memory_" + ts + ".jsonl").toString();
        try (var fw = new FileWriter(jsonlSimple)) {
            for (var r : allResults) {
                var entry = new LinkedHashMap<String, Object>();
                entry.put("question_id", r.get("question_id"));
                entry.put("hypothesis", r.get("hypothesis_simple"));
                fw.write(MAPPER.writeValueAsString(entry) + "\n");
            }
        }
        try (var fw = new FileWriter(jsonlMemory)) {
            for (var r : allResults) {
                var entry = new LinkedHashMap<String, Object>();
                entry.put("question_id", r.get("question_id"));
                entry.put("hypothesis", r.get("hypothesis_memory"));
                fw.write(MAPPER.writeValueAsString(entry) + "\n");
            }
        }
        System.out.println("SimpleAgent JSONL: " + jsonlSimple);
        System.out.println("MemoryAgent JSONL: " + jsonlMemory);
        System.out.println("\n使用官方评估脚本（需要 GPT-4o API Key）:");
        System.out.println("  python LongMemEval/src/evaluation/evaluate_qa.py gpt-4o " + jsonlMemory + " data/longmemeval/longmemeval_oracle");
    }

    // ═══════════════════════════════════════════════════════
    // Entry point
    // ═══════════════════════════════════════════════════════

    public static void main(String[] args) throws Exception {
        var config = BenchmarkConfig.fromArgs(args);

        // 从 classpath 读取 application.yml（兼容 IDE 运行和 JAR 运行）
        var yamlReader = new org.yaml.snakeyaml.Yaml();
        Map<String, Object> yamlConfig;
        var resourceStream = LongMemEvalBenchmark.class.getClassLoader().getResourceAsStream("application.yml");
        if (resourceStream == null) {
            System.out.println("警告: 未找到 application.yml，将使用默认配置");
            yamlConfig = Map.of("context-os", Map.of(
                "llm", Map.of("provider", "deepseek", "deepseek", Map.of("api-key", "", "model", "deepseek-chat")),
                "memory", Map.of("db-path", "./data/context_os.db")
            ));
        } else {
            try (var is = resourceStream) {
                yamlConfig = yamlReader.load(is);
            }
        }

        @SuppressWarnings("unchecked")
        var llmConfig = (Map<String, Object>) ((Map<String, Object>) yamlConfig.get("context-os")).get("llm");
        String provider = (String) llmConfig.get("provider");

        @SuppressWarnings("unchecked")
        var deepseekConfig = (Map<String, Object>) llmConfig.get("deepseek");
        String deepseekApiKey = (String) deepseekConfig.get("api-key");
        String deepseekModel = (String) deepseekConfig.get("model");

        @SuppressWarnings("unchecked")
        var memoryConfig = (Map<String, Object>) ((Map<String, Object>) yamlConfig.get("context-os")).get("memory");
        String dbPath = (String) memoryConfig.get("db-path");

        // 解析 ${DEEPSEEK_API_KEY:xxx} 占位符
        deepseekApiKey = resolvePlaceholder(deepseekApiKey);
        dbPath = resolvePlaceholder(dbPath);

        BaseLLMClient llmClient;
        switch (provider) {
            case "deepseek" -> {
                String envKey = System.getenv("DEEPSEEK_API_KEY");
                if (envKey != null && !envKey.isEmpty()) deepseekApiKey = envKey;
                if (deepseekApiKey == null || deepseekApiKey.isEmpty()) {
                    System.out.println("错误: 未检测到 DeepSeek API Key");
                    System.out.println("请在 application.yml 中配置 deepseek.api-key 或设置 DEEPSEEK_API_KEY 环境变量");
                    return;
                }
                llmClient = new DeepSeekClient(deepseekApiKey, deepseekModel, "https://api.deepseek.com/v1");
                System.out.println("使用 LLM: DeepSeek (" + deepseekModel + ")");
            }
            case "openai" -> {
                String envKey = System.getenv("OPENAI_API_KEY");
                if (envKey != null && !envKey.isEmpty()) {
                    @SuppressWarnings("unchecked")
                    var openaiConfig = (Map<String, Object>) llmConfig.get("openai");
                    String openaiModel = (String) openaiConfig.get("model");
                    llmClient = new OpenAIClient(envKey, openaiModel, "https://api.openai.com/v1");
                    System.out.println("使用 LLM: OpenAI (" + openaiModel + ")");
                } else {
                    System.out.println("错误: 未检测到 OpenAI API Key");
                    System.out.println("请设置 OPENAI_API_KEY 环境变量");
                    return;
                }
            }
            default -> {
                System.out.println("不支持的 LLM provider: " + provider);
                return;
            }
        }

        runBenchmark(config.dataPath(), llmClient, dbPath, config.maxEval(), config.outputDir(), config.skipSimple());
    }

    /** 解析 ${ENV_VAR:defaultValue} 占位符 */
    private static String resolvePlaceholder(String value) {
        if (value == null) return null;
        var matcher = java.util.regex.Pattern.compile("\\$\\{([^:}]+)(?::([^}]*))?\\}").matcher(value);
        if (matcher.matches()) {
            String envVar = matcher.group(1);
            String defaultValue = matcher.group(2);
            String envVal = System.getenv(envVar);
            return (envVal != null && !envVal.isEmpty()) ? envVal : defaultValue;
        }
        return value;
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }

    /** 基准测试运行配置 — 默认参数 + 命令行覆盖 */
    public record BenchmarkConfig(
            String dataPath,
            int maxEval,
            String outputDir,
            boolean skipSimple
    ) {
        public static BenchmarkConfig fromArgs(String[] args) {
            var dataPath = "data/longmemeval/longmemeval_oracle";
            var maxEval = 20;
            var outputDir = "results";
            var skipSimple = true;

            for (int i = 0; i < args.length; i++) {
                switch (args[i]) {
                    case "--data" -> dataPath = args[++i];
                    case "--max-eval" -> maxEval = Integer.parseInt(args[++i]);
                    case "--output-dir" -> outputDir = args[++i];
                    case "--skip-simple" -> skipSimple = true;
                }
            }
            return new BenchmarkConfig(dataPath, maxEval, outputDir, skipSimple);
        }
    }
}
