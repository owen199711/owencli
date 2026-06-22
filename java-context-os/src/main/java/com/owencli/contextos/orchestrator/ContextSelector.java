package com.owencli.contextos.orchestrator;

import com.owencli.contextos.core.model.IntentType;
import com.owencli.contextos.core.model.TaskSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * Dynamic context selector.
 * Decides which ContextFlag(s) to collect based on TaskSpec intent.
 */
public class ContextSelector {

    private static final Logger log = LoggerFactory.getLogger(ContextSelector.class);
    private static final int TIGHT_TOKEN_THRESHOLD = 8000;

    // Intent → Context flags mapping
    private static final Map<IntentType, Set<ContextFlag>> INTENT_CONTEXT_MAP;

    static {
        Map<IntentType, Set<ContextFlag>> map = new HashMap<>();
        map.put(IntentType.QA, EnumSet.of(ContextFlag.CONVERSATION, ContextFlag.MEMORY, ContextFlag.KNOWLEDGE));
        map.put(IntentType.CODING, EnumSet.of(ContextFlag.IDENTITY, ContextFlag.CONVERSATION, ContextFlag.ENVIRONMENT, ContextFlag.MEMORY, ContextFlag.TOOLS));
        map.put(IntentType.DEBUGGING, EnumSet.of(ContextFlag.IDENTITY, ContextFlag.CONVERSATION, ContextFlag.ENVIRONMENT, ContextFlag.MEMORY, ContextFlag.KNOWLEDGE, ContextFlag.TOOLS));
        map.put(IntentType.PLANNING, EnumSet.of(ContextFlag.CONVERSATION, ContextFlag.MEMORY, ContextFlag.KNOWLEDGE));
        map.put(IntentType.SEARCH, EnumSet.of(ContextFlag.MEMORY, ContextFlag.KNOWLEDGE));
        map.put(IntentType.WORKFLOW, EnumSet.of(ContextFlag.CONVERSATION, ContextFlag.MEMORY, ContextFlag.ENVIRONMENT, ContextFlag.TOOLS));
        map.put(IntentType.AGENT, EnumSet.of(ContextFlag.IDENTITY, ContextFlag.CONVERSATION, ContextFlag.ENVIRONMENT, ContextFlag.MEMORY, ContextFlag.KNOWLEDGE, ContextFlag.TOOLS));
        map.put(IntentType.DATA_ANALYSIS, EnumSet.of(ContextFlag.CONVERSATION, ContextFlag.MEMORY, ContextFlag.ENVIRONMENT, ContextFlag.TOOLS));
        INTENT_CONTEXT_MAP = Collections.unmodifiableMap(map);
    }

    public ContextSelector() {
        log.info("ContextSelector initialized with {} intent mappings", INTENT_CONTEXT_MAP.size());
    }

    /**
     * Select context flags based on task spec.
     */
    public Set<ContextFlag> select(TaskSpec task) {
        log.debug("Selecting context for task: intent={}, goal={}", task.getIntent().getValue(), task.getGoal().getValue());

        Set<ContextFlag> flags = new HashSet<>(INTENT_CONTEXT_MAP.getOrDefault(
                task.getIntent(), EnumSet.of(ContextFlag.CONVERSATION)));

        log.debug("Default flags for {}: {}", task.getIntent().getValue(), flags);

        // Token budget pruning
        if (task.getConstraint().getMaxTokens() != null &&
                task.getConstraint().getMaxTokens() < TIGHT_TOKEN_THRESHOLD) {
            log.info("Token budget tight ({} < {}), removing low-priority contexts",
                    task.getConstraint().getMaxTokens(), TIGHT_TOKEN_THRESHOLD);
            flags.remove(ContextFlag.MEMORY);
            flags.remove(ContextFlag.ENVIRONMENT);
        }

        // Domain adjustment
        if ("simple_qa".equals(task.getDomain())) {
            flags.remove(ContextFlag.TOOLS);
        }

        log.info("Context selection complete: {} (intent={}, domain={})",
                flags, task.getIntent().getValue(), task.getDomain());
        return flags;
    }
}
