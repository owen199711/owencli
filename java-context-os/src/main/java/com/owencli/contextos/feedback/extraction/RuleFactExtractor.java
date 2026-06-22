package com.owencli.contextos.feedback.extraction;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.regex.Pattern;

/**
 * Rule-based fact extractor — first line of defense.
 * <p>
 * Extremely fast (<1ms), zero LLM cost, fully controllable.
 * Handles common patterns like "我叫X", "以后叫我X", "我喜欢X".
 * <p>
 * When rules match, they return directly — no LLM needed.
 * When no rule matches, returns empty so the LLM extractor takes over.
 */
public class RuleFactExtractor {

    private static final Logger log = LoggerFactory.getLogger(RuleFactExtractor.class);

    private final List<FactRule> rules;

    public RuleFactExtractor() {
        this.rules = buildDefaultRules();
        log.info("RuleFactExtractor initialized with {} rules", rules.size());
    }

    public List<CandidateFact> extract(String input) {
        if (input == null || input.isBlank()) return List.of();

        var candidates = new ArrayList<CandidateFact>();
        for (var rule : rules) {
            var matcher = rule.pattern().matcher(input.trim());
            if (matcher.find()) {
                String value = matcher.group(1).trim();
                if (value.length() >= 1) {
                    candidates.add(new CandidateFact(
                            rule.type(),
                            value,
                            0.95,  // rule-based = high confidence
                            "rule:" + rule.name(),
                            rule.priority()
                    ));
                }
            }
        }
        // Return highest priority match only
        return candidates.stream()
                .min(Comparator.comparingInt(CandidateFact::priority)
                        .thenComparing(c -> -c.value().length()))
                .map(List::of)
                .orElse(List.of());
    }

    private List<FactRule> buildDefaultRules() {
        var rules = new ArrayList<FactRule>();

        // ── Identity / Name ──
        rules.add(new FactRule("name_default", "user.name", 1,
                Pattern.compile("(?:我|本人)(?:叫|的?名字是|的?姓名是|又称|又名)[：:\\s]*([\\u4e00-\\u9fff\\w]{1,20})")));
        rules.add(new FactRule("name_later", "user.name", 2,
                Pattern.compile("以后叫我([\\u4e00-\\u9fff\\w]{1,20})")));
        rules.add(new FactRule("name_renamed", "user.name", 3,
                Pattern.compile("(?:改名叫|改名为|现在叫|现在名字是)[：:\\s]*([\\u4e00-\\u9fff\\w]{1,20})")));
        rules.add(new FactRule("name_callme", "user.name", 4,
                Pattern.compile("(?:请叫我|可以叫我|称呼我)[：:\\s]*([\\u4e00-\\u9fff\\w]{1,20})")));

        // ── Language / Programming ──
        rules.add(new FactRule("language_default", "user.preferred_language", 5,
                Pattern.compile("(?:主要写|常用|主要用|平时用|我写|我用)([\\w+#]+)")));
        rules.add(new FactRule("language_skill", "user.preferred_language", 6,
                Pattern.compile("(?:我喜欢用|我擅长|我熟悉)([\\w+#]+)")));

        // ── Platform / Tools ──
        rules.add(new FactRule("platform_default", "user.preferred_platform", 7,
                Pattern.compile("(?:主要用|平时用|主要使用)(?:的)?(?:平台|工具|框架|技术栈)是[：:\\s]*([\\w/]+)")));
        rules.add(new FactRule("platform_dev", "user.preferred_platform", 8,
                Pattern.compile("我用([\\w/]+)(?:开发|做项目|写代码)")));

        // ── Location ──
        rules.add(new FactRule("location", "user.location", 10,
                Pattern.compile("(?:我住在|我来自|我在|我的城市是)[：:\\s]*([\\u4e00-\\u9fff\\w]{2,20})")));

        // ── Occupation ──
        rules.add(new FactRule("occupation_role", "user.occupation", 11,
                Pattern.compile("(?:我是|我的职业是|我从事|我的工作是)[：:\\s]*([\\u4e00-\\u9fff\\w]{2,20})")));
        rules.add(new FactRule("occupation_company", "user.occupation", 12,
                Pattern.compile("(?:我[在就]职于|我工作在)[：:\\s]*([\\u4e00-\\u9fff\\w]{2,30})")));

        return rules;
    }

    public record FactRule(String name, String type, int priority, Pattern pattern) {}
    public record CandidateFact(String type, String value, double confidence, String source, int priority) {}
}
