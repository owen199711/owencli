package com.owencli.contextos.memory;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Memory Manager — unified facade over 7 memory subsystems.
 * <p>
 * Architecture:
 * <pre>
 *                    Memory Manager
 *         ┌──────────────┐
 *         │ Working      │  Session, in-memory
 *         ├──────────────┤
 *         │ Conversation │  24h~30d TTL
 *         ├──────────────┤
 *         │ Episodic     │  Permanent, vectorized
 *         ├──────────────┤
 *         │ Semantic     │  Knowledge graph
 *         ├──────────────┤
 *         │ Fact         │  KV with versioning
 *         ├──────────────┤
 *         │ LearnedBehav │  Procedures + tool stats
 *         ├──────────────┤
 *         │ LongTerm     │  Base persistent storage
 *         └──────────────┘
 *
 *   LongTermIndex — global vector retrieval layer (queries across stores)
 * </pre>
 */
public class MemoryManager {

    private static final Logger log = LoggerFactory.getLogger(MemoryManager.class);

    private final WorkingMemory working;
    private final ConversationMemory conversation;
    private final EpisodicMemory episodic;
    private final SemanticMemory semantic;
    private final FactMemory fact;
    private final LearnedBehaviorMemory learnedBehavior;
    private final LongTermMemory longTerm;
    private final LongTermIndex index;

    public MemoryManager(WorkingMemory working, ConversationMemory conversation,
                         EpisodicMemory episodic, SemanticMemory semantic,
                         FactMemory fact, LearnedBehaviorMemory learnedBehavior,
                         LongTermMemory longTerm, LongTermIndex index) {
        this.working = working;
        this.conversation = conversation;
        this.episodic = episodic;
        this.semantic = semantic;
        this.fact = fact;
        this.learnedBehavior = learnedBehavior;
        this.longTerm = longTerm;
        this.index = index;
        log.info("MemoryManager initialized with 7 subsystems + LongTermIndex");
    }

    public WorkingMemory getWorking() { return working; }
    public ConversationMemory getConversation() { return conversation; }
    public EpisodicMemory getEpisodic() { return episodic; }
    public SemanticMemory getSemantic() { return semantic; }
    public FactMemory getFact() { return fact; }
    public LearnedBehaviorMemory getLearnedBehavior() { return learnedBehavior; }
    public LongTermMemory getLongTerm() { return longTerm; }
    public LongTermIndex getIndex() { return index; }
}
