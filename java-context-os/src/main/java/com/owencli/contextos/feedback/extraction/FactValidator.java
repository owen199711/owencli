package com.owencli.contextos.feedback.extraction;

import com.owencli.contextos.feedback.extraction.RuleFactExtractor.CandidateFact;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;

/**
 * Fact Validator — validates candidate facts before storage.
 * <p>
 * Filters out:
 * <ul>
 *   <li>Facts with too low confidence</li>
 *   <li>Facts that are temporary states (tired, hungry, etc.)</li>
 *   <li>Facts with empty/trivial values</li>
 * </ul>
 */
public class FactValidator {

    private static final Logger log = LoggerFactory.getLogger(FactValidator.class);
    private static final double MIN_CONFIDENCE = 0.4;
    private static final List<String> TEMPORARY_TYPES = List.of(
            "user.state", "user.mood", "user.feeling", "user.status"
    );
    private static final List<String> TRIVIAL_VALUES = List.of(
            "a", "an", "the", "this", "that", "yes", "no", "ok", "okay",
            "你好", "好的", "嗯", "是", "不是", "对", "不对"
    );

    public List<CandidateFact> validate(List<CandidateFact> candidates) {
        var validated = new ArrayList<CandidateFact>();
        for (var c : candidates) {
            if (c.confidence() < MIN_CONFIDENCE) {
                log.trace("Fact rejected: confidence too low ({}) for {}={}", c.confidence(), c.type(), c.value());
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
            validated.add(c);
        }
        if (validated.size() < candidates.size()) {
            log.info("FactValidator: removed {} invalid candidates (kept {})",
                    candidates.size() - validated.size(), validated.size());
        }
        return validated;
    }
}
