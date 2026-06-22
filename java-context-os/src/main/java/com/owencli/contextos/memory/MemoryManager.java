package com.owencli.contextos.memory;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Memory Manager — unified facade over all 10 memory subsystems.
 * <p>
 * Architecture:
 * <pre>
 *                    Memory Manager
 *         ┌──────────────┐
 *         │ Working      │
 *         ├──────────────┤
 *         │ Conversation │
 *         ├──────────────┤
 *         │ Task         │
 *         ├──────────────┤
 *         │ LongTerm     │
 *         ├──────────────┤
 *         │ Episodic     │
 *         ├──────────────┤
 *         │ Semantic     │
 *         ├──────────────┤
 *         │ Procedural   │
 *         ├──────────────┤
 *         │ Tool         │
 *         ├──────────────┤
 *         │ Reflection   │
 *         ├──────────────┤
 *         │ Fact         │
 *         └──────────────┘
 * </pre>
 */
public class MemoryManager {

    private static final Logger log = LoggerFactory.getLogger(MemoryManager.class);

    private final WorkingMemory working;
    private final ConversationMemory conversation;
    private final TaskMemory task;
    private final LongTermMemory longTerm;
    private final EpisodicMemory episodic;
    private final SemanticMemory semantic;
    private final ProceduralMemory procedural;
    private final ToolExperienceMemory tool;
    private final ReflectionMemory reflection;
    private final FactMemory fact;

    public MemoryManager(WorkingMemory working, ConversationMemory conversation,
                         TaskMemory task, LongTermMemory longTerm,
                         EpisodicMemory episodic, SemanticMemory semantic,
                         ProceduralMemory procedural, ToolExperienceMemory tool,
                         ReflectionMemory reflection, FactMemory fact) {
        this.working = working;
        this.conversation = conversation;
        this.task = task;
        this.longTerm = longTerm;
        this.episodic = episodic;
        this.semantic = semantic;
        this.procedural = procedural;
        this.tool = tool;
        this.reflection = reflection;
        this.fact = fact;
        log.info("MemoryManager initialized with 10 memory subsystems (incl. Fact)");
    }

    public WorkingMemory getWorking() { return working; }
    public ConversationMemory getConversation() { return conversation; }
    public TaskMemory getTask() { return task; }
    public LongTermMemory getLongTerm() { return longTerm; }
    public EpisodicMemory getEpisodic() { return episodic; }
    public SemanticMemory getSemantic() { return semantic; }
    public ProceduralMemory getProcedural() { return procedural; }
    public ToolExperienceMemory getTool() { return tool; }
    public ReflectionMemory getReflection() { return reflection; }
    public FactMemory getFact() { return fact; }
}
