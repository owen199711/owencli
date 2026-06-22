package com.owencli.contextos.collection;

import com.owencli.contextos.core.model.ConversationContext;
import com.owencli.contextos.core.model.ConversationTurn;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;

/**
 * Conversation history collector with circular buffer.
 */
public class ConversationCollector {

    private static final Logger log = LoggerFactory.getLogger(ConversationCollector.class);

    private final List<ConversationTurn> history = new ArrayList<>();
    private final int maxHistory;

    public ConversationCollector() {
        this(50);
    }

    public ConversationCollector(int maxHistory) {
        this.maxHistory = maxHistory;
        log.info("ConversationCollector initialized (max_history={})", maxHistory);
    }

    public List<ConversationTurn> getHistory() {
        return List.copyOf(history);
    }

    public int getTurnCount() {
        return history.size();
    }

    public void addTurn(String role, String content) {
        history.add(new ConversationTurn(role, content));
        if (history.size() > maxHistory) {
            var dropped = history.remove(0);
            log.debug("History buffer full, dropped oldest turn: role={}, content={}...",
                    dropped.getRole(), truncate(dropped.getContent(), 50));
        }
        log.debug("Added conversation turn: role={}, content_len={} (total={}/{})",
                role, content.length(), history.size(), maxHistory);
    }

    public void clear() {
        int count = history.size();
        history.clear();
        log.info("Cleared conversation history ({} turns dropped)", count);
    }

    public List<ConversationTurn> getRecent(int n) {
        int start = Math.max(0, history.size() - n);
        return history.subList(start, history.size());
    }

    public CompletableFuture<ConversationContext> collect() {
        log.debug("Collecting conversation context (total turns={})", history.size());
        var context = new ConversationContext();
        context.setHistory(new ArrayList<>(history));
        context.setStatus("running");
        log.info("Conversation context collected: turns={}, status={}",
                context.getHistory().size(), context.getStatus());
        return CompletableFuture.completedFuture(context);
    }

    private static String truncate(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max);
    }
}
