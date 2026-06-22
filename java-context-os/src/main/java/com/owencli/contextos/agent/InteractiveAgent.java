package com.owencli.contextos.agent;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.model.*;
import com.owencli.contextos.feedback.MemoryUpdateResult;
import com.owencli.contextos.llm.DeepSeekClient;
import com.owencli.contextos.llm.MockClient;
import com.owencli.contextos.core.model.MemoryItem;
import com.owencli.contextos.pipeline.ContextOSPipeline;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.Scanner;

/**
 * 对话式 Agent — 直接输入对话，自动触发记忆存储与检索。
 * <p>
 * 每次输入都会：
 * 1. 通过 Pipeline 处理 → 意图识别、记忆检索、LLM 回答
 * 2. 自动将对话存入 Working/ShortTerm/LongTerm 记忆
 * 3. 展示中间过程：上下文构建 → 上下文优化 → Prompt 打包
 * <p>
 * 特殊命令：
 *   /memory  — 查看各层记忆内容
 *   /clear   — 清空当前对话历史
 *   /debug   — 切换详细过程输出（默认开启）
 *   /help    — 显示帮助
 *   /exit    — 退出
 */
public class InteractiveAgent {

    private final ContextOSPipeline pipeline;
    private final Scanner scanner = new Scanner(System.in);
    private boolean running = true;
    private boolean showDebug = true;

    public InteractiveAgent() throws Exception {
        var llmClient = selectLlmClient();
        String ts = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"));
        this.pipeline = new ContextOSPipeline(
                llmClient, LLMProvider.DEEPSEEK, "./data/agent.db",
                "agent-" + ts, "interactive-user");
        pipeline.ensureStore().join();
    }

    private BaseLLMClient selectLlmClient() {
        System.out.println("=" .repeat(60));
        System.out.println("  Context-OS 交互式 Agent — 自动记忆对话");
        System.out.println("=" .repeat(60));
        System.out.println("选择 LLM:");
        System.out.println("  1. MockClient（无需 API Key，模拟回复）");
        System.out.println("  2. DeepSeek（需设置 DEEPSEEK_API_KEY）");
        System.out.print  ("请输入 [1/2] (默认 1): ");

        String choice = scanner.nextLine().trim();
        if ("2".equals(choice)) {
            String key = System.getenv("DEEPSEEK_API_KEY");
            if (key == null || key.isEmpty()) {
                System.out.print("输入 DeepSeek API Key: ");
                key = scanner.nextLine().trim();
            }
            if (!key.isEmpty()) {
                System.out.println("✅ 已选择 DeepSeek");
                return new DeepSeekClient(key, "deepseek-chat", "https://api.deepseek.com/v1");
            }
            System.out.println("⚠️  API Key 为空，回退到 MockClient");
        }
        System.out.println("✅ 已选择 MockClient（模拟回复）");
        return new MockClient();
    }

    public void run() {
        printHelp();
        while (running) {
            System.out.print("\n💬 你说: ");
            String input = scanner.nextLine().trim();

            if (input.isEmpty()) continue;

            if (input.startsWith("/")) {
                handleCommand(input);
                continue;
            }

            processInput(input);
        }
        pipeline.close().join();
        scanner.close();
    }

    @SuppressWarnings("unchecked")
    private void processInput(String input) {
        long t0 = System.currentTimeMillis();
        try {
            var result = pipeline.run(input).join();
            long latency = System.currentTimeMillis() - t0;

            // 提取结果
            String response = (String) result.get("response");
            var metrics = (EvalMetrics) result.get("metrics");
            var unified = (UnifiedContext) result.get("unified_context");
            var optimized = (OptimizedContext) result.get("optimized_context");
            var packaged = (PackagedContext) result.get("packaged_context");
            var task = (TaskSpec) result.get("task_spec");
            var memUpdate = (MemoryUpdateResult) result.get("memory_update");

            // ── 显示调试过程 ──
            if (showDebug) {
                showPipelineDebug(input, task, unified, optimized, packaged, memUpdate);
            }

            // ── 显示回复 ──
            boolean memoryRetrieved = metrics != null && metrics.getRewardScore() > 0;
            System.out.println("\n🤖 Agent: " + response);
            System.out.print("  ⏱ " + latency + "ms");
            if (memoryRetrieved) {
                System.out.print("  🧠 已检索记忆");
            }
            System.out.println();

        } catch (Exception e) {
            System.err.println("\n❌ 错误: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private void showPipelineDebug(String input, TaskSpec task,
                                   UnifiedContext unified,
                                   OptimizedContext optimized,
                                   PackagedContext packaged,
                                   MemoryUpdateResult memUpdate) {
        System.out.println("\n" + "─".repeat(60));
        System.out.println("📋 Pipeline 详细过程");
        System.out.println("─".repeat(60));

        // ── Step 1: 意图理解 ──
        System.out.println("\n🔹 Step 1: 意图理解 (Intent Understanding)");
        if (task != null) {
            System.out.println("    intent:     " + task.getIntent().getValue());
            System.out.println("    goal:       " + task.getGoal().getValue());
            System.out.println("    confidence: " + String.format("%.2f", task.getConfidence()));
            if (task.getEntities() != null && !task.getEntities().isEmpty()) {
                System.out.println("    entities:   " + task.getEntities().stream()
                        .map(e -> e.getType() + "=" + e.getValue()).reduce((a, b) -> a + ", " + b).orElse(""));
            }
        }

        // ── Step 2: 上下文构建 ──
        System.out.println("\n🔹 Step 2: 上下文构建 (Context Building) → UnifiedContext");
        if (unified != null) {
            // Identity
            System.out.print("    identity:   ");
            if (unified.getIdentity() != null) {
                System.out.println(unified.getIdentity().getUserId()
                        + " (" + unified.getIdentity().getRole() + ")");
            } else {
                System.out.println("❌ 无");
            }

            // Conversation
            System.out.print("    conversation: ");
            if (unified.getConversation() != null) {
                int n = unified.getConversation().getHistory().size();
                System.out.println(n + " 轮对话");
                if (n > 0) {
                    var last = unified.getConversation().getHistory()
                            .get(unified.getConversation().getHistory().size() - 1);
                    System.out.println("      最新轮: [" + last.getRole() + "] "
                            + truncate(last.getContent(), 80));
                }
            } else {
                System.out.println("❌ 无");
            }

            // Environment
            System.out.print("    environment: ");
            if (unified.getEnvironment() != null) {
                System.out.println("OS=" + unified.getEnvironment().getOs()
                        + ", CWD=" + unified.getEnvironment().getWorkingDirectory());
            } else {
                System.out.println("❌ 无");
            }

            // Memory (LTM + STM + Episodic retrieved)
            System.out.println("    retrieved_memory (LTM+STM+Episodic): " + unified.getMemory().size() + " 条");
            if (!unified.getMemory().isEmpty()) {
                for (int i = 0; i < unified.getMemory().size(); i++) {
                    var mem = unified.getMemory().get(i);
                    System.out.println("      └─ [" + (i + 1) + "] score="
                            + String.format("%.3f", mem.getRelevanceScore())
                            + "  " + truncate(mem.getContent(), 150));
                }
            } else {
                System.out.println("      (无匹配记忆)");
            }
        }

        // ── Step 3: 上下文优化 ──
        System.out.println("\n🔹 Step 3: 上下文优化 (Context Optimization) → OptimizedContext");
        if (optimized != null) {
            System.out.println("    compressed: " + optimized.isCompressed());
            var budget = optimized.getTokenUsage();
            if (budget != null) {
                System.out.println("    token_budget: total=" + budget.getTotal()
                        + ", used=" + budget.getUsed());
                if (budget.getBreakdown() != null && !budget.getBreakdown().isEmpty()) {
                    System.out.println("    breakdown:");
                    budget.getBreakdown().forEach((k, v) ->
                            System.out.println("      " + k + ": " + v));
                }
            }
        }

        // ── Step 4: Prompt 打包 ──
        System.out.println("\n🔹 Step 4: Prompt 打包 (Context Packaging) → PackagedContext");
        if (packaged != null) {
            System.out.println("    provider:   " + packaged.getProvider().getValue());
            System.out.println("    prompt_len: " + packaged.getRawPrompt().length() + " chars");

            var sections = packaged.getSections();
            if (sections != null && !sections.isEmpty()) {
                System.out.println("    sections:   " + String.join(", ", sections.keySet()));
                System.out.println();
                for (var entry : sections.entrySet()) {
                    System.out.println("    ┌─ [" + entry.getKey() + "] ──");
                    for (var line : entry.getValue().split("\n")) {
                        System.out.println("    │ " + line);
                    }
                    System.out.println("    └─");
                }
            }

            // 最终完整 prompt 预览
            System.out.println("\n    📄 最终完整 Prompt (前 1000 字符):");
            System.out.println("    " + "─".repeat(58));
            String prompt = packaged.getRawPrompt();
            if (prompt.length() > 1000) {
                System.out.println(prompt.substring(0, 1000));
                System.out.println("    ... (共 " + prompt.length() + " 字符，仅显示前 1000)");
            } else {
                System.out.println(prompt);
            }
            System.out.println("    " + "─".repeat(58));
        }

        // ── Step 6: 记忆更新 (Memory Update) ──
        System.out.println("\n🔹 Step 6: 记忆更新 (Memory Update)");
        if (memUpdate != null) {
            System.out.println("    " + "─".repeat(50));
            System.out.println("    │ 最终评分:             " + String.format("%.2f", memUpdate.getFinalScore())
                    + "  → " + memUpdate.getStorageTier().getName());
            System.out.println("    │  ┌─ 规则(Rule):       " + String.format("%.2f (权重0.20)", memUpdate.getRuleScore()));
            System.out.println("    │  ├─ 语义(Semantic):   " + String.format("%.2f (权重0.35)", memUpdate.getSemanticScore()));
            System.out.println("    │  ├─ 新颖(Novelty):    " + String.format("%.2f (权重0.20)", memUpdate.getNoveltyScore()));
            System.out.println("    │  ├─ 事实(FactWeight): " + String.format("%.2f (权重0.15)", memUpdate.getFactWeightScore()));
            System.out.println("    │  └─ 目标(Goal):       " + String.format("%.2f (权重0.10)", memUpdate.getGoalRelationScore()));
            System.out.println("    │");
            System.out.println("    │ 写入 WorkingMemory:   ✅ (Always)");
            System.out.println("    │ 写入 Conversation:    ✅ (Always, TTL="
                    + (memUpdate.isSavedToLTM() ? "永久)" : "24h~30天)"));
            System.out.println("    │ 升级 LongTermMemory:  " + (memUpdate.isSavedToLTM() ? "✅" : "❌")
                    + " (需要 ≥" + com.owencli.contextos.importances.StorageTier.EPISODE_LTM.getMinScore() + ")");
            System.out.println("    │ 写入 EpisodicMemory:  " + (memUpdate.isSavedToEpisodic() ? "✅" : "❌"));
            System.out.println("    │ 更新 SemanticMemory:  " + (memUpdate.isSavedToSemantic() ? "✅" : "❌"));
            System.out.println("    │ 提取结构化事实:       " + (memUpdate.getFactsSaved() > 0 ?
                    "✅ " + memUpdate.getFactsSaved() + " 条" : "❌"));
            if (memUpdate.isWasDuplicate()) {
                System.out.println("    │ ⚠️ 重复检测:         已合并");
            }
            if (memUpdate.isHasConflict()) {
                System.out.println("    │ ⚠️ 冲突检测:         存在矛盾");
            }
            System.out.println("    │ 耗时:                 " + memUpdate.getElapsedMs() + "ms");
            System.out.println("    " + "─".repeat(50));
            System.out.println("    ▶ " + memUpdate.summary());
        } else {
            System.out.println("    (无记忆更新数据)");
        }

        System.out.println("─".repeat(60));
    }

    private void handleCommand(String cmd) {
        switch (cmd.toLowerCase()) {
            case "/memory", "/m" -> showMemories();
            case "/clear", "/c" -> {
                pipeline.getConversationCollector().clear();
                pipeline.getWorkingMemory().clear();
                System.out.println("✅ 对话历史与工作记忆已清空");
            }
            case "/debug", "/d" -> {
                showDebug = !showDebug;
                System.out.println(showDebug ? "✅ 详细过程输出已开启" : "🔇 详细过程输出已关闭");
            }
            case "/help", "/h" -> printHelp();
            case "/exit", "/quit", "/q" -> {
                running = false;
                System.out.println("👋 再见！");
            }
            default -> System.out.println("未知命令。输入 /help 查看帮助。");
        }
    }

    private void showMemories() {
        System.out.println("\n" + "=".repeat(60));
        System.out.println("  记忆系统状态 (Memory System Status)");
        System.out.println("=".repeat(60));

        var mm = pipeline.getMemoryManager();

        // 1. Working Memory
        var wm = pipeline.getWorkingMemory();
        System.out.println("\n📝 Working Memory (运行中活跃上下文):");
        System.out.println("  条目数: " + wm.getItemCount() + "  |  Token: "
                + wm.getTokenUsage() + "/" + wm.getMaxTokens());
        if (wm.getItemCount() > 0) {
            for (var item : wm.getRecent(5)) {
                System.out.println("    • " + truncate(item.getContent(), 120));
            }
        }

        // 2. Conversation Memory
        printMemoryList("💬 Conversation Memory (对话历史, 24h TTL)", () ->
                mm.getConversation().getRecent(10).join(), "条目数");

        // 3. Task Memory
        printMemoryList("📋 Task Memory (任务执行记录)", () ->
                mm.getTask().getRecentTasks(10).join(), "条目数");

        // 4. LongTerm Memory
        printMemoryList("🧠 LongTerm Memory (长期知识)", () ->
                mm.getLongTerm().retrieve("", 20, null, null).join(), "条目数");

        // 5. Episodic Memory
        printMemoryList("🎬 Episodic Memory (过往经验)", () ->
                mm.getEpisodic().recallSimilar("", 10).join(), "条目数");

        // 6. Semantic Memory
        System.out.println("\n🔗 Semantic Memory (知识图谱概念):");
        try {
            var graph = mm.getSemantic().queryGraph("", 1).join();
            var nodes = (java.util.List<?>) graph.getOrDefault("nodes", java.util.List.of());
            var edges = (java.util.List<?>) graph.getOrDefault("edges", java.util.List.of());
            System.out.println("  概念数: " + nodes.size() + "  |  关系数: " + edges.size());
            for (var n : nodes) {
                if (n instanceof java.util.Map<?, ?> m) {
                    System.out.println("    • " + m.get("name") + " (" + m.get("type") + ")");
                }
            }
        } catch (Exception e) {
            System.out.println("  ⚠️ " + e.getMessage());
        }

        // 7. Procedural Memory
        printMemoryList("⚙️ Procedural Memory (学习的工作流程)", () ->
                mm.getProcedural().retrieve("", null, 10).join(), "条目数");

        // 8. Reflection Memory
        printMemoryList("🪞 Reflection Memory (自我反思与教训)", () ->
                mm.getReflection().retrieve("", 10).join(), "条目数");

        // 9. Tool Experience Memory
        System.out.println("\n🔧 Tool Experience Memory (工具使用经验):");
        try {
            var stats = mm.getTool().getToolStats("").join();
            System.out.println("  工具数(有记录): " + stats.getOrDefault("total_executions", 0));
        } catch (Exception e) {
            System.out.println("  ⚠️ " + e.getMessage());
        }

        // 10. Fact Memory
        System.out.println("\n📌 Fact Memory (结构化用户事实):");
        try {
            var facts = mm.getFact().getAllFacts().join();
            System.out.println("  事实数: " + facts.size());
            for (var f : facts) {
                if (f.isActive()) {
                    System.out.println("    • " + f.getType() + " = " + f.getCurrentValue()
                            + " (confidence=" + String.format("%.2f", f.getConfidence())
                            + ", status=" + f.getStatus() + ")");
                }
            }
        } catch (Exception e) {
            System.out.println("  ⚠️ " + e.getMessage());
        }

        // Database
        var dbFile = new java.io.File("./data/agent.db");
        if (dbFile.exists()) {
            System.out.println("\n💾 数据库文件: " + dbFile.getAbsolutePath()
                    + " (" + (dbFile.length() / 1024) + " KB)");
        }
        System.out.println("=".repeat(60));
    }

    @FunctionalInterface
    private interface MemorySupplier {
        java.util.List<MemoryItem> get() throws Exception;
    }

    private void printMemoryList(String title, MemorySupplier supplier, String countLabel) {
        System.out.println("\n" + title + ":");
        try {
            var items = supplier.get();
            System.out.println("  " + countLabel + ": " + items.size());
            for (var item : items) {
                String tag = "[" + item.getType().getValue() + "]";
                if (item.getType() == MemoryType.FACT) {
                    tag = "[fact]";
                }
                System.out.println("    • " + tag + " score="
                        + String.format("%.3f", item.getRelevanceScore())
                        + "  " + truncate(item.getContent(), 120));
            }
        } catch (Exception e) {
            System.out.println("  ⚠️ " + e.getMessage());
        }
    }

    private void printHelp() {
        System.out.println("\n直接输入文字即可对话，系统会自动展示完整的处理过程。");
        System.out.println("\n特殊命令:");
        System.out.println("  ┌──────────┬────────────────────────────────────┐");
        System.out.println("  │ /memory  │ 查看记忆系统状态                   │");
        System.out.println("  │ /clear   │ 清空当前对话历史                   │");
        System.out.println("  │ /debug   │ 切换详细过程输出                    │");
        System.out.println("  │ /help    │ 显示帮助                          │");
        System.out.println("  │ /exit    │ 退出                              │");
        System.out.println("  └──────────┴────────────────────────────────────┘");
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) + "..." : (s != null ? s : "");
    }

    public static void main(String[] args) throws Exception {
        new InteractiveAgent().run();
    }
}
