package com.owencli.contextos.optimizer;

import com.owencli.contextos.core.model.MemoryItem;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.stream.Collectors;

/**
 * Noise Filter — removes irrelevant or low-quality memory items.
 * Filters out greeting messages, empty content, and noise.
 */
public class NoiseFilter {

    private static final Logger log = LoggerFactory.getLogger(NoiseFilter.class);

    private static final List<String> GREETING_PATTERNS = List.of(
            "hi", "hello", "hey", "你好", "嗨", "早上好", "下午好", "晚上好",
            "thanks", "thank you", "谢谢", "bye", "再见", "ok", "okay",
            "好的", "嗯", "yes", "no", "是", "不是", "test", "测试"
    );

    public List<MemoryItem> filter(List<MemoryItem> items) {
        int before = items.size();

        var filtered = items.stream()
                .filter(item -> item.getContent() != null && !item.getContent().isBlank())
                .filter(item -> item.getContent().length() >= 5)
                .filter(item -> !isNoise(item.getContent()))
                .collect(Collectors.toList());

        int removed = before - filtered.size();
        if (removed > 0) {
            log.info("NoiseFilter: removed {} noise items ({} → {})", removed, before, filtered.size());
        }
        return filtered;
    }

    private boolean isNoise(String content) {
        String trimmed = content.trim().toLowerCase();
        return GREETING_PATTERNS.stream().anyMatch(p -> trimmed.equals(p) || trimmed.matches("^" + p + "[\\s!.,]*$"));
    }
}
