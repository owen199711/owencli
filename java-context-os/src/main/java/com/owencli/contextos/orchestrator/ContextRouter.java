package com.owencli.contextos.orchestrator;

import com.owencli.contextos.core.model.TaskSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Context router.
 * Converts ContextFlag combinations into prioritized route lists.
 */
public class ContextRouter {

    private static final Logger log = LoggerFactory.getLogger(ContextRouter.class);

    private static final List<ContextRoute> DEFAULT_ROUTES = List.of(
            new ContextRoute("conversation_store", ContextFlag.CONVERSATION, 90),
            new ContextRoute("identity_provider", ContextFlag.IDENTITY, 80),
            new ContextRoute("memory_store", ContextFlag.MEMORY, 70),
            new ContextRoute("knowledge_store", ContextFlag.KNOWLEDGE, 60),
            new ContextRoute("env_provider", ContextFlag.ENVIRONMENT, 50),
            new ContextRoute("tool_registry", ContextFlag.TOOLS, 40)
    );

    public ContextRouter() {
        log.info("ContextRouter initialized with {} default routes", DEFAULT_ROUTES.size());
    }

    /**
     * Convert ContextFlag set into priority-sorted route list.
     */
    public List<ContextRoute> route(TaskSpec task, Set<ContextFlag> flags) {
        log.debug("Routing context: flags={}, task={}", flags, task.getId());

        // Filter and sort by priority descending
        List<ContextRoute> routes = DEFAULT_ROUTES.stream()
                .filter(r -> flags.contains(r.getFlag()))
                .sorted(Comparator.comparingInt(ContextRoute::getPriority).reversed())
                .collect(Collectors.toList());

        // Prune if token budget is limited
        if (task.getConstraint().getMaxTokens() != null &&
                task.getConstraint().getMaxTokens() < 16000) {
            int maxRoutes = task.getConstraint().getMaxTokens() < 8000 ? 3 : 5;
            if (routes.size() > maxRoutes) {
                log.info("Token budget limited ({}), reducing routes from {} to {}",
                        task.getConstraint().getMaxTokens(), routes.size(), maxRoutes);
                routes = routes.subList(0, maxRoutes);
            }
        }

        log.info("Routing result: {} routes selected", routes.size());
        for (ContextRoute route : routes) {
            log.debug("  Route: source={}, priority={}", route.getSource(), route.getPriority());
        }
        return routes;
    }
}
