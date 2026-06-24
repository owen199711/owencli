package com.owencli.contextos.feedback.extraction;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.regex.Pattern;

import static java.util.regex.Pattern.CASE_INSENSITIVE;

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

        // ═══════════════════════════════════════════════
        // Identity / Name
        // ═══════════════════════════════════════════════
        // Chinese
        rules.add(new FactRule("name_default", "user.name", 1,
                Pattern.compile("(?:我|本人)(?:叫|的?名字是|的?姓名是|又称|又名)[：:\\s]*([\\u4e00-\\u9fff\\w]{1,20})")));
        rules.add(new FactRule("name_later", "user.name", 2,
                Pattern.compile("以后叫我([\\u4e00-\\u9fff\\w]{1,20})")));
        rules.add(new FactRule("name_renamed", "user.name", 3,
                Pattern.compile("(?:改名叫|改名为|现在叫|现在名字是)[：:\\s]*([\\u4e00-\\u9fff\\w]{1,20})")));
        rules.add(new FactRule("name_callme", "user.name", 4,
                Pattern.compile("(?:请叫我|可以叫我|称呼我)[：:\\s]*([\\u4e00-\\u9fff\\w]{1,20})")));
        // English
        rules.add(new FactRule("name_my_name_is", "user.name", 2,
                Pattern.compile("my name is ([A-Za-z ]{1,30})", CASE_INSENSITIVE)));
        rules.add(new FactRule("name_im", "user.name", 3,
                Pattern.compile("i['’]?m (?:called |named )?([A-Za-z ]{1,30})", CASE_INSENSITIVE)));
        rules.add(new FactRule("name_call_me", "user.name", 3,
                Pattern.compile("(?:call me|you can call me|please call me) ([A-Za-z ]{1,30})", CASE_INSENSITIVE)));
        rules.add(new FactRule("name_go_by", "user.name", 4,
                Pattern.compile("(?:i go by|everyone calls me|they call me) ([A-Za-z ]{1,30})", CASE_INSENSITIVE)));

        // ═══════════════════════════════════════════════
        // Language / Programming
        // ═══════════════════════════════════════════════
        // Chinese
        rules.add(new FactRule("language_default", "user.preferred_language", 5,
                Pattern.compile("(?:主要写|常用|主要用|平时用|我写|我用)([\\w+#]+)")));
        rules.add(new FactRule("language_skill", "user.preferred_language", 6,
                Pattern.compile("(?:我喜欢用|我擅长|我熟悉)([\\w+#]+)")));
        // English
        rules.add(new FactRule("language_write", "user.preferred_language", 5,
                Pattern.compile("i (?:primarily |mostly |mainly )?(?:write|use|code in|program in) ([A-Za-z+#]+)", CASE_INSENSITIVE)));
        rules.add(new FactRule("language_prefer", "user.preferred_language", 6,
                Pattern.compile("(?:i prefer|i like|i love) (?:using |writing |coding in )?([A-Za-z+#]+)", CASE_INSENSITIVE)));
        rules.add(new FactRule("language_expert", "user.preferred_language", 6,
                Pattern.compile("i['’]?m (?:proficient in|good at|skilled in|familiar with) ([A-Za-z+#]+)", CASE_INSENSITIVE)));

        // ═══════════════════════════════════════════════
        // Platform / Tools
        // ═══════════════════════════════════════════════
        // Chinese
        rules.add(new FactRule("platform_default", "user.preferred_platform", 7,
                Pattern.compile("(?:主要用|平时用|主要使用)(?:的)?(?:平台|工具|框架|技术栈)是[：:\\s]*([\\w/]+)")));
        rules.add(new FactRule("platform_dev", "user.preferred_platform", 8,
                Pattern.compile("我用([\\w/]+)(?:开发|做项目|写代码)")));
        // English
        rules.add(new FactRule("platform_use", "user.preferred_platform", 7,
                Pattern.compile("i (?:primarily |mostly |mainly )?use ([A-Za-z0-9/]+) (?:for|to|as my)", CASE_INSENSITIVE)));
        rules.add(new FactRule("platform_work_with", "user.preferred_platform", 8,
                Pattern.compile("i (?:work with|develop on|build on) ([A-Za-z0-9/]+)", CASE_INSENSITIVE)));

        // ═══════════════════════════════════════════════
        // Location
        // ═══════════════════════════════════════════════
        rules.add(new FactRule("location", "user.location", 10,
                Pattern.compile("(?:我住在|我来自|我在|我的城市是)[：:\\s]*([\\u4e00-\\u9fff\\w]{2,20})")));
        rules.add(new FactRule("location_en", "user.location", 10,
                Pattern.compile("(?:i live in|i['’]?m from|i['’]?m based in|located in) ([A-Za-z ]{2,30})", CASE_INSENSITIVE)));

        // ═══════════════════════════════════════════════
        // Occupation
        // ═══════════════════════════════════════════════
        // Chinese
        rules.add(new FactRule("occupation_role", "user.occupation", 11,
                Pattern.compile("(?:我是|我的职业是|我从事|我的工作是)[：:\\s]*([\\u4e00-\\u9fff\\w]{2,20})")));
        rules.add(new FactRule("occupation_company", "user.occupation", 12,
                Pattern.compile("(?:我[在就]职于|我工作在)[：:\\s]*([\\u4e00-\\u9fff\\w]{2,30})")));
        // English
        rules.add(new FactRule("occupation_am", "user.occupation", 11,
                Pattern.compile("i['’]?m an? (software|backend|frontend|full.stac[kx]|data|devops|platform|systems|site.reliability|security|machine learning|ai|research|product|staff|principal|lead|senior|junior).{0,40}(?:engineer|developer|designer|architect|manager)", CASE_INSENSITIVE)));
        rules.add(new FactRule("occupation_work_as", "user.occupation", 12,
                Pattern.compile("(?:i work as|i serve as|i['’]?m a) (.{2,40})", CASE_INSENSITIVE)));
        rules.add(new FactRule("occupation_company_en", "user.company", 12,
                Pattern.compile("(?:i work at|i work for|i['’]?m employed by|i join) ([A-Za-z0-9 .]{2,40})", CASE_INSENSITIVE)));

        // ═══════════════════════════════════════════════
        // Skill (English-specific)
        // ═══════════════════════════════════════════════
        rules.add(new FactRule("skill_experience", "user.skill", 13,
                Pattern.compile("i have \\d+ years? of experience (?:with|in) ([A-Za-z]+)", CASE_INSENSITIVE)));
        rules.add(new FactRule("skill_knowledge", "user.skill", 14,
                Pattern.compile("i (?:know|have experience with|specialize in) ([A-Za-z0-9/ ]{2,40})", CASE_INSENSITIVE)));

        log.info("RuleFactExtractor: {} rules loaded (Chinese + English)", rules.size());
        return rules;
    }

    public record FactRule(String name, String type, int priority, Pattern pattern) {}
    public record CandidateFact(String type, String value, double confidence, String source, int priority) {}
}
