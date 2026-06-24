package com.owencli.contextos.feedback.extraction;

import com.owencli.contextos.feedback.extraction.RuleFactExtractor.CandidateFact;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Fact Validator — validates candidate facts before storage.
 * <p>
 * Detects Correction/Reinforcement signals to override confidence.
 * <p>
 * Correction: user says "不对", "you misunderstood", "try again" → confidence ≥ 0.95
 * Reinforcement: user says "就是这样", "perfect", "keep doing that" → confidence ≥ 0.9
 */
public class FactValidator {

    private static final Logger log = LoggerFactory.getLogger(FactValidator.class);
    private static final double MIN_CONFIDENCE = 0.4;

    // Chinese correction patterns
    private static final Pattern CORRECTION_CN = Pattern.compile(
            "不对|不是|不正确|你说错了|你理解错了|搞错了|重试|重新来|不是这样|换一种|改用|错了");
    // English correction patterns
    private static final Pattern CORRECTION_EN = Pattern.compile(
            "(?i)(that'?s? wrong|that'?s? incorrect|you misunderstood|try again|redo|not correct|not right|my mistake)");

    // Chinese reinforcement patterns
    private static final Pattern REINFORCEMENT_CN = Pattern.compile(
            "就是这样|完全正确|就是这个意思|正是我想要的|厉害了|没错|继续保持");
    // English reinforcement patterns
    private static final Pattern REINFORCEMENT_EN = Pattern.compile(
            "(?i)(yes[ ,]+exactly|that'?s? right|that'?s? correct|perfect|great|keep doing that|nailed it|spot on)");

    private static final List<String> TEMPORARY_TYPES = List.of(
            "user.state", "user.mood", "user.feeling", "user.status"
    );
    private static final List<String> TRIVIAL_VALUES = List.of(
            "a", "an", "the", "this", "that", "yes", "no", "ok", "okay",
            "你好", "好的", "嗯", "是", "不是", "对", "不对"
    );

    public List<CandidateFact> validate(List<CandidateFact> candidates, String input) {
        var validated = new ArrayList<CandidateFact>();

        // Detect correction/reinforcement signals
        boolean isCorrection = input != null && (
                CORRECTION_CN.matcher(input).find() || CORRECTION_EN.matcher(input).find());
        boolean isReinforcement = input != null && (
                REINFORCEMENT_CN.matcher(input).find() || REINFORCEMENT_EN.matcher(input).find());

        for (var c : candidates) {
            // Apply signal-based confidence override
            double confidence = c.confidence();
            String source = c.source();

            if (isCorrection) {
                confidence = Math.max(confidence, 0.95);
                source = "correction_signal";
                log.info("Correction signal detected for {}={} → confidence={}", c.type(), c.value(), confidence);
            } else if (isReinforcement) {
                confidence = Math.max(confidence, 0.90);
                source = "reinforcement_signal";
                log.info("Reinforcement signal detected for {}={} → confidence={}", c.type(), c.value(), confidence);
            }

            if (confidence < MIN_CONFIDENCE) {
                log.trace("Fact rejected: confidence too low ({}) for {}={}", confidence, c.type(), c.value());
                continue;
            }
            if (TEMPORARY_TYPES.contains(c.type())) {
                log.trace("Fact rejected: temporary type {}={}", c.type(), c.value());
                continue;
            }
            if (c.value() == null || c.value().isBlank() || TRIVIAL_VALUES.contains(c.value().trim().toLowerCase())) {
                log.trace("Fact rejected: trivial value={}", c.value());
                continue;
            }

            // Override with signal-adjusted values
            if (confidence != c.confidence() || !source.equals(c.source())) {
                validated.add(new CandidateFact(c.type(), c.value(), confidence, source, c.priority()));
            } else {
                validated.add(c);
            }
        }

        if (validated.size() < candidates.size()) {
            log.info("FactValidator: removed {} invalid candidates (kept {})",
                    candidates.size() - validated.size(), validated.size());
        }
        return validated;
    }

    // Backward-compatible overload
    public List<CandidateFact> validate(List<CandidateFact> candidates) {
        return validate(candidates, "");
    }
}
