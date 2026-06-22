package com.owencli.contextos.importances;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;

/**
 * Fact Weight Scorer — assigns weight based on detected fact type in content.
 * <p>
 * Not all information is equally important as long-term memory.
 * Identity facts (name, company) should score high. Temporary states (tired, hungry) should not.
 * <p>
 * Weight in final score: 0.15.
 */
public class FactWeightScorer {

    private static final Logger log = LoggerFactory.getLogger(FactWeightScorer.class);

    private static final Map<String, Double> FACT_TYPE_WEIGHTS = Map.ofEntries(
            Map.entry("identity",     1.00),  // 姓名、身份
            Map.entry("company",      0.95),  // 公司、组织
            Map.entry("occupation",   0.95),  // 职位、职业
            Map.entry("skill",        0.90),  // 技能栈
            Map.entry("preference",   0.90),  // 偏好、喜好
            Map.entry("location",     0.85),  // 位置
            Map.entry("project",      0.85),  // 项目
            Map.entry("goal",         0.90),  // 长期目标
            Map.entry("tool",         0.80),  // 工具偏好
            Map.entry("task",         0.70),  // 任务
            Map.entry("opinion",      0.60),  // 观点
            Map.entry("state",        0.20),  // 临时状态
            Map.entry("temporary",    0.15),  // 临时信息
            Map.entry("greeting",     0.05)   // 问候
    );

    public double score(String content) {
        if (content == null || content.isBlank()) return 0.0;

        String lower = content.toLowerCase();
        double maxWeight = 0.0;

        // Check for identity declarations
        if (content.contains("我叫") || content.contains("名字") || content.contains("姓名")
                || lower.contains("my name") || lower.contains("i am")) {
            maxWeight = Math.max(maxWeight, FACT_TYPE_WEIGHTS.getOrDefault("identity", 1.0));
        }

        // Check for company/organization
        if (content.contains("公司") || content.contains("就职") || content.contains("工作")
                || lower.contains("company") || lower.contains("employ") || lower.contains("work at")) {
            maxWeight = Math.max(maxWeight, FACT_TYPE_WEIGHTS.getOrDefault("company", 0.95));
        }

        // Check for skills
        if (lower.contains("擅长") || lower.contains("熟悉") || lower.contains("熟练")
                || lower.contains("skill") || lower.contains("proficient")) {
            maxWeight = Math.max(maxWeight, FACT_TYPE_WEIGHTS.getOrDefault("skill", 0.90));
        }

        // Check for preferences
        if (content.contains("喜欢") || content.contains("热爱") || content.contains("偏好")
                || lower.contains("prefer") || lower.contains("like") || lower.contains("love")) {
            maxWeight = Math.max(maxWeight, FACT_TYPE_WEIGHTS.getOrDefault("preference", 0.90));
        }

        // Check for location
        if (content.contains("住在") || content.contains("来自") || content.contains("城市")
                || lower.contains("live in") || lower.contains("from")) {
            maxWeight = Math.max(maxWeight, FACT_TYPE_WEIGHTS.getOrDefault("location", 0.85));
        }

        // Check for projects/goals
        if (content.contains("项目") || content.contains("开发") || content.contains("目标")
                || lower.contains("project") || lower.contains("goal")) {
            maxWeight = Math.max(maxWeight, FACT_TYPE_WEIGHTS.getOrDefault("project", 0.85));
        }

        // Check for temporary states
        if (content.contains("累") || content.contains("饿") || content.contains("困")
                || lower.contains("tired") || lower.contains("hungry") || lower.contains("sleepy")) {
            maxWeight = Math.max(maxWeight, FACT_TYPE_WEIGHTS.getOrDefault("state", 0.20));
        }

        // Check for greetings
        boolean isGreeting = content.trim().length() <= 10 && (
                lower.matches("^(hi|hello|hey|你好|嗨|thanks|thank you|谢谢|ok|yes|no|嗯|好的).*")
        );
        if (isGreeting) {
            maxWeight = Math.max(maxWeight, FACT_TYPE_WEIGHTS.getOrDefault("greeting", 0.05));
        }

        return Math.min(1.0, maxWeight);
    }
}
