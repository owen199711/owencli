package com.owencli.contextos.intent;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.core.model.GoalType;
import com.owencli.contextos.core.model.IntentType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CompletableFuture;

public class IntentClassifier {
    private static final Logger log = LoggerFactory.getLogger(IntentClassifier.class);
    private static final List<KeywordRule> INTENT_RULES = Arrays.asList(
            new KeywordRule(Arrays.asList("debug","fix","bug","crash","error","issue","修复","错误","异常"), IntentType.DEBUGGING, GoalType.FIX, 0.7),
            new KeywordRule(Arrays.asList("write","create","implement","code","generate","编写","创建","实现"), IntentType.CODING, GoalType.GENERATE, 0.7),
            new KeywordRule(Arrays.asList("refactor","重构","重写","优化"), IntentType.CODING, GoalType.REFACTOR, 0.7),
            new KeywordRule(Arrays.asList("search","find","lookup","查询","搜索","查找"), IntentType.SEARCH, GoalType.EXPLAIN, 0.7),
            new KeywordRule(Arrays.asList("plan","设计","方案","计划","架构"), IntentType.PLANNING, GoalType.GENERATE, 0.7),
            new KeywordRule(Arrays.asList("explain","what is","什么是","介绍","解释","how to"), IntentType.QA, GoalType.EXPLAIN, 0.7),
            new KeywordRule(Arrays.asList("summarize","总结","摘要","概括"), IntentType.QA, GoalType.SUMMARIZE, 0.7),
            new KeywordRule(Arrays.asList("compare","区别","对比","vs","versus"), IntentType.QA, GoalType.COMPARE, 0.7),
            new KeywordRule(Arrays.asList("analyze","分析","数据分析","chart","图表"), IntentType.DATA_ANALYSIS, GoalType.EXPLAIN, 0.7),
            new KeywordRule(Arrays.asList("workflow","流程","自动化","pipeline"), IntentType.WORKFLOW, GoalType.GENERATE, 0.7)
    );
    private static final String CLASSIFY_PROMPT =
            "Classify the following user request into intent and goal categories.\n" +
            "Available intents: {intents}\nAvailable goals: {goals}\n" +
            "Return ONLY valid JSON with fields: intent, goal, confidence\n" +
            "User: {userInput}\nJSON:";

    private final BaseLLMClient llmClient;

    public IntentClassifier() { this(null); }
    public IntentClassifier(BaseLLMClient llmClient) { this.llmClient = llmClient; }

    public CompletableFuture<ClassificationResult> classify(String userInput) {
        if (llmClient != null) {
            return classifyWithLlm(userInput).exceptionally(e -> classifyWithRules(userInput));
        }
        return CompletableFuture.completedFuture(classifyWithRules(userInput));
    }

    private ClassificationResult classifyWithRules(String input) {
        String lower = input.toLowerCase();
        ClassificationResult best = new ClassificationResult(IntentType.QA, GoalType.EXPLAIN, 0.5);
        double bestScore = 0;
        for (var rule : INTENT_RULES) {
            long match = rule.keywords.stream().filter(lower::contains).count();
            if (match > 0) {
                double score = Math.min(rule.baseConfidence + match * 0.1, 0.95);
                if (score > bestScore) { bestScore = score; best = new ClassificationResult(rule.intent, rule.goal, score); }
            }
        }
        return best;
    }

    private CompletableFuture<ClassificationResult> classifyWithLlm(String input) {
        String intents = String.join(", ", Arrays.stream(IntentType.values()).map(IntentType::getValue).toList());
        String goals = String.join(", ", Arrays.stream(GoalType.values()).map(GoalType::getValue).toList());
        String prompt = CLASSIFY_PROMPT.replace("{intents}", intents).replace("{goals}", goals).replace("{userInput}", input);
        return llmClient.complete(prompt, null, 200, 0.3, "json")
                .thenApply(response -> {
                    try {
                        com.fasterxml.jackson.databind.JsonNode json;
                        if (response instanceof String s) json = MAPPER.readTree(s);
                        else json = (com.fasterxml.jackson.databind.JsonNode) response;
                        return new ClassificationResult(
                                IntentType.fromValue(json.get("intent").asText()),
                                GoalType.fromValue(json.get("goal").asText()),
                                json.has("confidence") ? json.get("confidence").asDouble() : 0.8);
                    } catch (Exception e) { throw new RuntimeException("Failed to parse LLM response", e); }
                });
    }

    private static final com.fasterxml.jackson.databind.ObjectMapper MAPPER = new com.fasterxml.jackson.databind.ObjectMapper();

    public record ClassificationResult(IntentType intent, GoalType goal, double confidence) {}
    private record KeywordRule(List<String> keywords, IntentType intent, GoalType goal, double baseConfidence) {}
}
