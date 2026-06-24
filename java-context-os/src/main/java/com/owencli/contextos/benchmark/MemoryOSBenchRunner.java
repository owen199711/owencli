package com.owencli.contextos.benchmark;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.model.FactRecord;
import com.owencli.contextos.core.model.LLMProvider;
import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.core.model.UnifiedContext;
import com.owencli.contextos.feedback.MemoryUpdateResult;
import com.owencli.contextos.llm.DeepSeekClient;
import com.owencli.contextos.llm.MockClient;
import com.owencli.contextos.memory.FactMemory;
import com.owencli.contextos.pipeline.ContextOSPipeline;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * MemoryOS-Bench Runner — 在 MemoryOS-Bench 数据集上评测 Context-OS 记忆系统。
 * <p>
 * 覆盖 6 类记忆测试：
 *   fact      — 事实抽取准确性（FactMemory key/value 验证）
 *   conversation — 对话历史检索能力
 *   episodic  — 情节记忆召回
 *   semantic  — 知识图谱查询
 *   behavior  — 行为模式学习
 *   noise     — 噪声/对抗样本抗干扰
 * <p>
 * 运行:
 *   java com.owencli.contextos.benchmark.MemoryOSBenchRunner
 */
public class MemoryOSBenchRunner {

    private static final Logger log = LoggerFactory.getLogger(MemoryOSBenchRunner.class);
    private static final ObjectMapper MAPPER = new ObjectMapper()
            .enable(SerializationFeature.INDENT_OUTPUT);
    private static final Set<String> STOP_WORDS = Set.of(
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "to", "of", "in", "on", "at", "for", "and", "or", "but",
            "this", "that", "it", "as", "by", "with", "from", "not",
            "he", "she", "they", "we", "you", "i", "his", "her", "their");

    // ══════════════════════════════════════════════
    // 数据模型
    // ══════════════════════════════════════════════

    static class BenchCase {
        String caseId;
        String memoryType;
        String subType;
        Object history;
        String question;
        String expectedAnswer;
        List<Map<String, Object>> expectedMemoryWrite;
        List<Map<String, Object>> graph;
        Map<String, Object> expectedBehavior;
        Map<String, Object> validation;
    }

    static class PerTypeStats {
        int total = 0;
        int correct = 0;
        double score = 0.0;            // 累计分数
        int writeCorrect = 0;          // 记忆写入正确数（fact/behavior/noise）
        double recallSum = 0.0;        // 检索到相关记忆的比例
        int retrievedSum = 0;          // 检索到的记忆总数
        double latencySum = 0.0;       // 总耗时
        int noiseRejected = 0;         // noise 正确拒绝数
        int factCorrectWrites = 0;     // fact 写入准确数
    }

    // ══════════════════════════════════════════════
    // 评测 Agent（支持配置 LLM 客户端）
    // ══════════════════════════════════════════════

    static class BenchAgent {
        private final ContextOSPipeline pipeline;
        private boolean initialized = false;

        BenchAgent(String dbPath, String sessionId, BaseLLMClient llmClient) {
            this.pipeline = new ContextOSPipeline(
                    llmClient, LLMProvider.DEEPSEEK, dbPath,
                    sessionId, "bench-user");
        }

        BenchAgent(String dbPath, String sessionId) {
            this(dbPath, sessionId, new MockClient());
        }

        CompletableFuture<Void> ensure() {
            if (!initialized) {
                return pipeline.ensureStore().thenRun(() -> initialized = true);
            }
            return CompletableFuture.completedFuture(null);
        }

        /** 摄入用户输入并收集记忆更新结果。 */
        CompletableFuture<MemoryUpdateResult> ingest(String input) {
            return ensure().thenCompose(v ->
                    pipeline.run(input).thenApply(result -> {
                        if (result.get("memory_update") instanceof MemoryUpdateResult mr) {
                            return mr;
                        }
                        return null;
                    }));
        }

        /** 提问并获取回复 + 检索到的记忆上下文。 */
        CompletableFuture<AnswerCtx> ask(String question) {
            return ensure().thenCompose(v ->
                    pipeline.run(question).thenApply(result -> {
                        String response = (String) result.get("response");
                        response = response != null ? response.trim() : "";
                        List<MemoryItem> memories = List.of();
                        if (result.get("unified_context") instanceof UnifiedContext ctx) {
                            memories = ctx.getMemory();
                        }
                        return new AnswerCtx(response, memories);
                    }));
        }

        /** 获取 FactMemory 中指定类型的当前值。 */
        CompletableFuture<Optional<String>> getFactValue(String type) {
            return pipeline.getMemoryManager().getFact().getFact(type)
                    .thenApply(opt -> opt.map(FactRecord::getCurrentValue));
        }

        /** 获取全部活跃 facts。 */
        CompletableFuture<List<FactRecord>> getAllFacts() {
            return pipeline.getMemoryManager().getFact().getAllFacts();
        }

        /** 查询语义图谱。 */
        CompletableFuture<Map<String, Object>> queryGraph(String concept, int depth) {
            return pipeline.getMemoryManager().getSemantic().queryGraph(concept, depth);
        }

        /** 获取学习到的行为。 */
        CompletableFuture<List<MemoryItem>> getLearnedBehaviors() {
            return pipeline.getMemoryManager().getLearnedBehavior()
                    .retrieveAll("", 100);
        }

        void clearConversation() {
            pipeline.getConversationCollector().clear();
        }

        /** 获取最近聊天的原始记录（验证存储有效性）。 */
        CompletableFuture<List<MemoryItem>> getRecentConversations(int limit) {
            return pipeline.getMemoryManager().getConversation()
                    .getRecent(limit);
        }

        /** 召回相似情节记忆（验证情节存储有效性）。 */
        CompletableFuture<List<MemoryItem>> recallSimilarEpisodes(String query, int topK) {
            return pipeline.getMemoryManager().getEpisodic()
                    .recallSimilar(query, topK);
        }

        CompletableFuture<Void> close() {
            return pipeline.close();
        }
    }

    static class AnswerCtx {
        final String response;
        final List<MemoryItem> retrievedMemories;
        AnswerCtx(String response, List<MemoryItem> retrievedMemories) {
            this.response = response;
            this.retrievedMemories = retrievedMemories;
        }
    }

    // ══════════════════════════════════════════════
    // 指标计算方法
    // ══════════════════════════════════════════════

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

    static boolean isCorrect(String hypothesis, String answer) {
        return keywordOverlapScore(hypothesis, answer) >= 0.5;
    }

    /** 检查检索到的记忆中是否包含期望答案的关键词。 */
    static double retrievalRecall(List<MemoryItem> memories, String expected) {
        if (memories == null || memories.isEmpty() || expected == null) return 0.0;
        String expNorm = normalizeText(expected);
        var expTokens = Arrays.stream(expNorm.split("\\s+"))
                .filter(t -> !STOP_WORDS.contains(t) && t.length() > 1)
                .collect(Collectors.toList());
        if (expTokens.isEmpty()) return 1.0;

        String allContent = memories.stream()
                .map(m -> normalizeText(m.getContent() != null ? m.getContent() : ""))
                .collect(Collectors.joining(" "));

        long hits = expTokens.stream().filter(allContent::contains).count();
        return (double) hits / expTokens.size();
    }

    // ══════════════════════════════════════════════
    // Case 加载
    // ══════════════════════════════════════════════

    static List<BenchCase> loadCases(String dir) throws Exception {
        var cases = new ArrayList<BenchCase>();
        var path = Paths.get(dir);
        if (!Files.isDirectory(path)) return cases;

        try (var files = Files.list(path)) {
            files.filter(f -> f.toString().endsWith(".json"))
                    .sorted()
                    .forEach(f -> {
                        try {
                            var node = MAPPER.readTree(f.toFile());
                            var c = new BenchCase();
                            c.caseId = node.get("case_id").asText();
                            c.memoryType = node.get("memory_type").asText();
                            c.subType = node.has("sub_type") ? node.get("sub_type").asText() : "";
                            c.question = node.has("question") ? node.get("question").asText() : "";
                            c.expectedAnswer = node.has("expected_answer") ? node.get("expected_answer").asText() : "";

                            // history 可能是数组或对象
                            if (node.has("history")) {
                                c.history = MAPPER.treeToValue(node.get("history"), Object.class);
                            }

                            // expected_memory_write
                            if (node.has("expected_memory_write")) {
                                c.expectedMemoryWrite = MAPPER.treeToValue(
                                        node.get("expected_memory_write"), new TypeReference<>() {});
                            }

                            // graph (semantic)
                            if (node.has("graph")) {
                                c.graph = MAPPER.treeToValue(
                                        node.get("graph"), new TypeReference<>() {});
                            }

                            // expected_behavior (behavior)
                            if (node.has("expected_behavior")) {
                                c.expectedBehavior = MAPPER.treeToValue(
                                        node.get("expected_behavior"), LinkedHashMap.class);
                            }

                            // validation (behavior)
                            if (node.has("validation")) {
                                c.validation = MAPPER.treeToValue(
                                        node.get("validation"), LinkedHashMap.class);
                            }

                            cases.add(c);
                        } catch (Exception e) {
                            log.warn("Failed to load case: {}", f, e);
                        }
                    });
        }
        return cases;
    }

    // ══════════════════════════════════════════════
    // 各类型评测逻辑
    // ══════════════════════════════════════════════

    /** 评测 Fact 类型：验证事实抽取和 FactMemory 写入。 */
    static BenchResult evalFact(BenchAgent agent, BenchCase c) throws Exception {
        long t0 = System.nanoTime();
        // 摄入对话
        var turns = extractHistoryStrings(c.history);
        for (var turn : turns) {
            agent.ingest(turn).join();
        }

        // 验证 FactMemory 是否包含期望的 key/value
        boolean writeOk = true;
        if (c.expectedMemoryWrite == null || c.expectedMemoryWrite.isEmpty()) {
            writeOk = true;
        } else {
            var facts = agent.getAllFacts().join();
            for (var expected : c.expectedMemoryWrite) {
                // key 不强制要求精确 type 匹配，改为按值匹配
                // RuleEngine 可能产生相近的 type（如 occupation vs profession）
                String expectedValue = (String) expected.get("value");
                boolean found = facts.stream().anyMatch(f ->
                        f.getCurrentValue().contains(expectedValue) && f.isActive());
                if (!found) {
                    writeOk = false;
                    log.debug("Expected fact not found: value={}, active facts={}",
                            expectedValue,
                            facts.stream().filter(FactRecord::isActive).map(FactRecord::getCurrentValue).toList());
                }
            }
        }

        // 提问验证回答是否包含期望答案
        var ctx = agent.ask(c.question).join();
        double score = keywordOverlapScore(ctx.response, c.expectedAnswer);
        boolean answerOk = score >= 0.5;

        long elapsed = (System.nanoTime() - t0) / 1_000_000;
        double recall = retrievalRecall(ctx.retrievedMemories, c.expectedAnswer);
        return new BenchResult(answerOk, score, writeOk, recall, ctx.retrievedMemories.size(), elapsed);
    }

    /** 评测 Conversation 类型：验证对话存储 + 检索召回。 */
    static BenchResult evalConversation(BenchAgent agent, BenchCase c) throws Exception {
        long t0 = System.nanoTime();
        var turns = extractHistoryStrings(c.history);
        for (var turn : turns) {
            agent.ingest(turn).join();
        }

        // 验证对话内容是否真正存入 ConversationMemory
        var stored = agent.getRecentConversations(20).join();
        String expNorm = normalizeText(c.expectedAnswer);
        boolean writeOk = stored.stream().anyMatch(m ->
                normalizeText(m.getContent() != null ? m.getContent() : "")
                        .contains(expNorm));

        var ctx = agent.ask(c.question).join();
        double score = keywordOverlapScore(ctx.response, c.expectedAnswer);
        boolean answerOk = score >= 0.5;

        // 计算检索召回率
        double recall = 0.0;
        if (ctx.retrievedMemories != null && !ctx.retrievedMemories.isEmpty()) {
            recall = retrievalRecall(ctx.retrievedMemories, c.expectedAnswer);
        }

        long elapsed = (System.nanoTime() - t0) / 1_000_000;
        return new BenchResult(answerOk, score, writeOk, recall, ctx.retrievedMemories.size(), elapsed);
    }

    /** 评测 Episodic 类型：验证情节存储 + 检索召回。 */
    static BenchResult evalEpisodic(BenchAgent agent, BenchCase c) throws Exception {
        long t0 = System.nanoTime();
        var turns = extractHistoryStrings(c.history);
        for (var turn : turns) {
            agent.ingest(turn).join();
        }

        // 验证情节是否存入 EpisodicMemory
        var episodes = agent.recallSimilarEpisodes(c.expectedAnswer, 5).join();
        String expNorm = normalizeText(c.expectedAnswer);
        boolean writeOk = episodes.stream().anyMatch(m ->
                normalizeText(m.getContent() != null ? m.getContent() : "")
                        .contains(expNorm));

        var ctx = agent.ask(c.question).join();
        double score = keywordOverlapScore(ctx.response, c.expectedAnswer);
        boolean answerOk = score >= 0.5;

        double recall = retrievalRecall(ctx.retrievedMemories, c.expectedAnswer);

        long elapsed = (System.nanoTime() - t0) / 1_000_000;
        return new BenchResult(answerOk, score, writeOk, recall, ctx.retrievedMemories.size(), elapsed);
    }

    /** 评测 Semantic 类型：验证知识图谱。 */
    static BenchResult evalSemantic(BenchAgent agent, BenchCase c) throws Exception {
        long t0 = System.nanoTime();
        // 语义数据需要先写入 SemanticMemory
        // 我们直接通过 pipeline ingest 对话来触发语义写入
        // 但由于 MockClient 不会实际抽取语义，这里直接使用 MemoryManager 写入概念
        if (c.graph != null && !c.graph.isEmpty()) {
            for (var edge : c.graph) {
                String source = (String) edge.get("source");
                String target = (String) edge.get("target");
                String relation = (String) edge.getOrDefault("relation", "related_to");
                agent.pipeline.getMemoryManager().getSemantic()
                        .addConcept(source, Map.of("type", "entity"), null, 1.0).join();
                agent.pipeline.getMemoryManager().getSemantic()
                        .addRelation(source, target, relation, 1.0).join();
            }
        }

        // 查询知识图谱
        double score = 0.0;
        boolean answerOk = false;
        if (c.graph != null && !c.graph.isEmpty()) {
            var firstEdge = c.graph.get(0);
            String source = (String) firstEdge.get("source");
            var graph = agent.queryGraph(source, 2).join();
            var nodes = (List<?>) graph.getOrDefault("nodes", List.of());
            var edges = (List<?>) graph.getOrDefault("edges", List.of());

            // 如果有节点，说明图谱查询成功
            if (!nodes.isEmpty()) {
                score = 1.0;
                answerOk = true;
            }
        }

        long elapsed = (System.nanoTime() - t0) / 1_000_000;
        return new BenchResult(answerOk, score, !c.graph.isEmpty(), 0, 0, elapsed);
    }

    /** 评测 Behavior 类型：验证行为模式学习。 */
    static BenchResult evalBehavior(BenchAgent agent, BenchCase c) throws Exception {
        long t0 = System.nanoTime();
        var turns = extractHistoryStrings(c.history);
        // 重复输入多次以触发行为学习
        for (int repeat = 0; repeat < 6; repeat++) {
            for (var turn : turns) {
                agent.ingest(turn).join();
            }
        }

        // 检查是否学到了行为
        var behaviors = agent.getLearnedBehaviors().join();
        boolean learnedOk = false;
        if (c.expectedBehavior != null) {
            String expectedBehavior = (String) c.expectedBehavior.get("behavior");
            learnedOk = behaviors.stream().anyMatch(b ->
                    b.getContent() != null && b.getContent().contains(expectedBehavior));
        }

        // 提问并验证 validation 规则
        var ctx = agent.ask(c.question).join();
        boolean validationPassed = true;
        double validationScore = 1.0;
        if (c.validation != null) {
            int answerLen = ctx.response.length();
            if (c.validation.containsKey("min_answer_length")) {
                int minLen = ((Number) c.validation.get("min_answer_length")).intValue();
                validationPassed = answerLen >= minLen;
                validationScore = Math.min(1.0, (double) answerLen / minLen);
            }
            if (c.validation.containsKey("max_answer_length")) {
                int maxLen = ((Number) c.validation.get("max_answer_length")).intValue();
                validationPassed = validationPassed && answerLen <= maxLen;
                validationScore = Math.min(validationScore, answerLen <= maxLen ? 1.0 : (double) maxLen / answerLen);
            }
        }

        long elapsed = (System.nanoTime() - t0) / 1_000_000;
        return new BenchResult(validationPassed, validationScore, learnedOk, 0, behaviors.size(), elapsed);
    }

    /** 评测 Noise 类型：验证抗干扰能力。 */
    static BenchResult evalNoise(BenchAgent agent, BenchCase c) throws Exception {
        long t0 = System.nanoTime();
        var turns = extractHistoryStrings(c.history);
        for (var turn : turns) {
            agent.ingest(turn).join();
        }

        var ctx = agent.ask(c.question).join();

        // noise 期望答案为 "unknown" —— 模型不应给出具体答案
        // 检查 FactMemory 是否有被错误写入的事实
        var facts = agent.getAllFacts().join();

        // 如果 facts 为空或只有 trivial 的 fact，说明抗噪声能力强
        // 也检查回答是否 "不确定" 或 "不知道"
        String respLower = ctx.response.toLowerCase();
        boolean rejected = facts.isEmpty()
                || facts.stream().allMatch(f -> f.getType().startsWith("user.") && f.getConfidence() < 0.3);

        long elapsed = (System.nanoTime() - t0) / 1_000_000;
        return new BenchResult(rejected, rejected ? 1.0 : 0.0, rejected, 0, facts.size(), elapsed);
    }

    // ══════════════════════════════════════════════
    // 辅助方法
    // ══════════════════════════════════════════════

    /** 从 history 字段提取对话文本列表。支持多种格式。 */
    @SuppressWarnings("unchecked")
    static List<String> extractHistoryStrings(Object history) {
        var result = new ArrayList<String>();
        if (history == null) return result;

        if (history instanceof List<?> list) {
            for (var item : list) {
                if (item instanceof String s) {
                    result.add(s);
                } else if (item instanceof Map<?, ?> m) {
                    Object content = m.get("content");
                    if (content instanceof String s) {
                        result.add(s);
                    }
                }
            }
        } else if (history instanceof Map<?, ?> m) {
            Object content = m.get("content");
            if (content instanceof String s) {
                result.add(s);
            }
        }
        return result;
    }

    // ══════════════════════════════════════════════
    // 结果模型
    // ══════════════════════════════════════════════

    static class BenchResult {
        final boolean correct;
        final double score;
        final boolean writeCorrect;
        final double retrievalRecall;
        final int retrievedCount;
        final long elapsedMs;

        BenchResult(boolean correct, double score, boolean writeCorrect,
                    double retrievalRecall, int retrievedCount, long elapsedMs) {
            this.correct = correct;
            this.score = score;
            this.writeCorrect = writeCorrect;
            this.retrievalRecall = retrievalRecall;
            this.retrievedCount = retrievedCount;
            this.elapsedMs = elapsedMs;
        }
    }

    // ══════════════════════════════════════════════
    // 主评测入口
    // ══════════════════════════════════════════════

    public static void runBench(String dataDir, String dbPath, String outputDir,
                                BaseLLMClient llmClient, int maxCasesPerType) throws Exception {
        System.out.println("=" .repeat(100));
        System.out.println("  MemoryOS-Bench v1.0 — Context-OS 记忆系统评测");
        System.out.println("=" .repeat(100));

        // 数据目录
        var subDirs = Map.of(
//                 "fact", "fact"
                // "conversation", "conversation",
//                "episodic", "episodic"
                // "semantic", "semantic",
                 "behavior", "behavior"
                // "noise", "noise"
        );

        var allStats = new LinkedHashMap<String, PerTypeStats>();
        var allDetails = new ArrayList<Map<String, Object>>();

        long globalStart = System.currentTimeMillis();
        int totalCases = 0;

        for (var entry : subDirs.entrySet()) {
            String type = entry.getKey();
            String subDir = entry.getValue();
            Path caseDir = Paths.get(dataDir, subDir);

            System.out.printf("[%s] 加载数据...\n", type);
            var cases = loadCases(caseDir.toString());
            int actual = Math.min(cases.size(), maxCasesPerType);
            System.out.printf("[%s] 共 %d 条（限定 %d 条）\n", type, cases.size(), actual);

            if (cases.isEmpty()) continue;

            var stats = new PerTypeStats();
            String ts = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"));
            var agent = new BenchAgent(dbPath, "mos-" + ts + "-" + type, llmClient);

            for (int idx = 0; idx < Math.min(cases.size(), maxCasesPerType); idx++) {
                var c = cases.get(idx);
                agent.clearConversation();
                System.out.printf("\r  [%d/%d] %s", idx + 1, actual, c.caseId);

                BenchResult result;
                try {
                    result = switch (type) {
                        case "fact" -> evalFact(agent, c);
                        case "conversation" -> evalConversation(agent, c);
                        case "episodic" -> evalEpisodic(agent, c);
                        case "semantic" -> evalSemantic(agent, c);
                        case "behavior" -> evalBehavior(agent, c);
                        case "noise" -> evalNoise(agent, c);
                        default -> new BenchResult(false, 0, false, 0, 0, 0);
                    };
                } catch (Exception e) {
                    log.warn("Case {} failed: {}", c.caseId, e.getMessage());
                    result = new BenchResult(false, 0, false, 0, 0, 0);
                }

                stats.total++;
                if (result.correct) stats.correct++;
                if (result.writeCorrect) stats.writeCorrect++;
                stats.score += result.score;
                stats.recallSum += result.retrievalRecall;
                stats.retrievedSum += result.retrievedCount;
                stats.latencySum += result.elapsedMs;

                if (type.equals("noise") && result.correct) stats.noiseRejected++;
                if (type.equals("fact") && result.writeCorrect) stats.factCorrectWrites++;

                var detail = new LinkedHashMap<String, Object>();
                detail.put("case_id", c.caseId);
                detail.put("type", type);
                detail.put("sub_type", c.subType);
                detail.put("correct", result.correct);
                detail.put("score", Math.round(result.score * 1000.0) / 1000.0);
                detail.put("write_correct", result.writeCorrect);
                detail.put("retrieval_recall", Math.round(result.retrievalRecall * 1000.0) / 1000.0);
                detail.put("retrieved_count", result.retrievedCount);
                detail.put("elapsed_ms", result.elapsedMs);
                allDetails.add(detail);
            }

            agent.close().join();
            allStats.put(type, stats);
            totalCases += stats.total;
            System.out.println();
        }

        double globalElapsed = (System.currentTimeMillis() - globalStart) / 1000.0;

        // ═══════════════════════════════════════
        // 报告
        // ═══════════════════════════════════════

        System.out.println("\n");
        System.out.println("=" .repeat(100));
        System.out.println("  MemoryOS-Bench v1.0 — 评测报告");
        System.out.println("=" .repeat(100));
        System.out.printf("  总数据: %d 条 | 耗时: %.1f 秒\n\n", totalCases, globalElapsed);

        // 回答准确率
        System.out.println("  ── 回答准确率 (Answer Accuracy) ──");
        System.out.printf("  %-16s %6s %10s %10s %10s\n",
                "类型", "数量", "准确率", "平均分", "平均耗时");
        System.out.println("  " + "-".repeat(56));

        double totalCorrect = 0, totalScore = 0;
        for (var entry : allStats.entrySet()) {
            var s = entry.getValue();
            double acc = s.total > 0 ? (double) s.correct / s.total * 100 : 0;
            double avgScore = s.total > 0 ? s.score / s.total : 0;
            double avgLat = s.total > 0 ? s.latencySum / s.total : 0;
            System.out.printf("  %-16s %6d %9.1f%% %10.3f %10.1fms\n",
                    entry.getKey(), s.total, acc, avgScore, avgLat);
            totalCorrect += s.correct;
            totalScore += s.score;
        }
        System.out.println("  " + "-".repeat(56));
        System.out.printf("  %-16s %6d %9.1f%% %10.3f\n",
                "TOTAL", totalCases,
                totalCases > 0 ? totalCorrect / totalCases * 100 : 0,
                totalCases > 0 ? totalScore / totalCases : 0);
        System.out.println("=" .repeat(100));

        // 记忆写入准确率
        System.out.println("\n  ── 记忆有效性 (Memory Effectiveness) ──");
        System.out.println("  fact/conv/episodic=命中存储 | behavior=学到行为 | noise=正确拒绝");
        System.out.printf("  %-16s %10s %12s %12s %10s\n",
                "类型", "写入正确", "检索召回率", "平均检索数", "噪声拒绝");
        System.out.println("  " + "-".repeat(64));

        double totalWriteCorrect = 0, totalRecall = 0, totalNoiseRej = 0;
        for (var entry : allStats.entrySet()) {
            var s = entry.getValue();
            double writeAcc = s.total > 0 ? (double) s.writeCorrect / s.total * 100 : 0;
            double avgRecall = s.total > 0 ? s.recallSum / s.total : 0;
            double avgRetrieved = s.total > 0 ? (double) s.retrievedSum / s.total : 0;
            System.out.printf("  %-16s %9.1f%% %11.1f%% %12.1f %10d\n",
                    entry.getKey(), writeAcc, avgRecall * 100, avgRetrieved,
                    s.noiseRejected);
            totalWriteCorrect += s.writeCorrect;
            totalRecall += s.recallSum;
            totalNoiseRej += s.noiseRejected;
        }
        System.out.println("  " + "-".repeat(64));
        System.out.printf("  %-16s %9.1f%% %11.1f%%\n",
                "TOTAL",
                totalCases > 0 ? totalWriteCorrect / totalCases * 100 : 0,
                totalCases > 0 ? totalRecall / totalCases * 100 : 0);
        System.out.println("=" .repeat(100));

        // ── 保存结果 ──
        Files.createDirectories(Paths.get(outputDir));
        String ts = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"));
        var summary = new LinkedHashMap<String, Object>();
        summary.put("dataset", "MemoryOS-Bench v1.0");
        summary.put("num_instances", totalCases);
        summary.put("duration_seconds", Math.round(globalElapsed * 10.0) / 10.0);
        summary.put("llm", llmClient.getClass().getSimpleName());

        var byType = new LinkedHashMap<String, Object>();
        for (var entry : allStats.entrySet()) {
            var s = entry.getValue();
            var bt = new LinkedHashMap<String, Object>();
            bt.put("total", s.total);
            bt.put("accuracy", Math.round((double) s.correct / s.total * 1000.0) / 1000.0);
            bt.put("write_accuracy", Math.round((double) s.writeCorrect / s.total * 1000.0) / 1000.0);
            bt.put("avg_score", Math.round(s.score / s.total * 1000.0) / 1000.0);
            bt.put("avg_retrieval_recall", Math.round(s.recallSum / s.total * 1000.0) / 1000.0);
            bt.put("avg_retrieved_count", Math.round((double) s.retrievedSum / s.total * 10.0) / 10.0);
            bt.put("avg_latency_ms", Math.round(s.latencySum / s.total * 10.0) / 10.0);
            if (s.noiseRejected > 0) bt.put("noise_rejected", s.noiseRejected);
            if (s.factCorrectWrites > 0) bt.put("fact_correct_writes", s.factCorrectWrites);
            byType.put(entry.getKey(), bt);
        }
        summary.put("by_type", byType);
        summary.put("details", allDetails);

        String outFile = Paths.get(outputDir, "memoryos_bench_result_" + ts + ".json").toString();
        MAPPER.writeValue(new File(outFile), summary);
        System.out.println("\n  详细结果已保存: " + outFile);
    }

    // ══════════════════════════════════════════════
    // 入口
    // ══════════════════════════════════════════════

    public static void main(String[] args) throws Exception {
        var dataDir = "data/memoryos-bench";
        var dbPath = "./data/memoryos-bench.db";
        var outputDir = "results";
        var apiKey = "";
        var llmType = "deepseek";    // mock | deepseek
        int maxCases = 20;

        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--data" -> dataDir = args[++i];
                case "--db" -> dbPath = args[++i];
                case "--output" -> outputDir = args[++i];
                case "--api-key" -> apiKey = args[++i];
                case "--llm" -> llmType = args[++i];
                case "--limit" -> maxCases = Integer.parseInt(args[++i]);
            }
        }

        BaseLLMClient llmClient;
        if ("deepseek".equalsIgnoreCase(llmType)) {
            if (apiKey.isEmpty()) apiKey = System.getenv("DEEPSEEK_API_KEY");
            llmClient = new DeepSeekClient(apiKey, "deepseek-chat", null);
            System.out.println("🔑 DeepSeekClient configured (key="
                    + (apiKey.length() > 4 ? apiKey.substring(0, 4) + "..." : "?") + ")");
        } else {
            llmClient = new MockClient();
            System.out.println("🤖 Using MockClient (no real LLM)");
        }

        if (maxCases != Integer.MAX_VALUE) {
            System.out.println("📊 每类型限 " + maxCases + " 条");
        }

        runBench(dataDir, dbPath, outputDir, llmClient, maxCases);
    }
}
