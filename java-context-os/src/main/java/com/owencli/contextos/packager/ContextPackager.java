package com.owencli.contextos.packager;

import com.owencli.contextos.core.model.LLMProvider;
import com.owencli.contextos.core.model.OptimizedContext;
import com.owencli.contextos.core.model.PackagedContext;
import com.owencli.contextos.optimizer.PromptLayout;
import com.owencli.contextos.packager.adapters.AdapterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Context Packager — transforms optimized context into LLM-specific prompts.
 * <p>
 * Architecture:
 * <pre>
 * Packager
 *         │
 *         ▼
 *   System Prompt  ── Identity + Role
 *         │
 *         ▼
 *      Memory    ── Conversation + Memories
 *         │
 *         ▼
 *    Knowledge   ── Facts + Concepts
 *         │
 *         ▼
 *       Tool     ── Available tools
 *         │
 *         ▼
 *      Task      ── Current task instruction
 *         │
 *         ▼
 * Output Schema  ── Expected response format
 *         │
 *         ▼
 *    Guardrail   ── Safety constraints
 *         │
 *         ▼
 *       LLM
 * </pre>
 */
public class ContextPackager {

    private static final Logger log = LoggerFactory.getLogger(ContextPackager.class);

    private final AdapterRegistry registry;
    private final PromptLayout promptLayout;

    public ContextPackager() {
        this(new AdapterRegistry(), new PromptLayout());
    }

    public ContextPackager(AdapterRegistry registry, PromptLayout promptLayout) {
        this.registry = registry;
        this.promptLayout = promptLayout;
        log.info("ContextPackager initialized with PromptLayout");
    }

    public PackagedContext pack(OptimizedContext context, LLMProvider provider) {
        // First, use PromptLayout to structure the prompt
        var layoutPackage = promptLayout.layout(context, provider);

        // Then, apply provider-specific adapter
        var adapter = registry.get(provider);
        var adapted = adapter.pack(context);

        // Merge: use adapted sections but keep the layout structure
        var mergedSections = layoutPackage.getSections();
        mergedSections.putAll(adapted.getSections());
        layoutPackage.setSections(mergedSections);

        // Use the adapter's prompt if it's different
        if (!adapted.getRawPrompt().equals(layoutPackage.getRawPrompt())) {
            // Prefer the layout's structured prompt but let adapter customize
            layoutPackage.setRawPrompt(adapted.getRawPrompt());
        }

        log.info("Context packed: provider={}, prompt_len={} chars, sections={}",
                provider.getValue(), layoutPackage.getRawPrompt().length(), layoutPackage.getSections().size());
        return layoutPackage;
    }
}
