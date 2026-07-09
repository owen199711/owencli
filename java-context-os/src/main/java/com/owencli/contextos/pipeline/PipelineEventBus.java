package com.owencli.contextos.pipeline;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Consumer;

public class PipelineEventBus {
    private static final Logger log = LoggerFactory.getLogger(PipelineEventBus.class);
    private final Map<Class<?>, List<Consumer<?>>> handlers = new ConcurrentHashMap<>();

    @SuppressWarnings("unchecked")
    public <E extends PipelineEvent> void register(Class<E> eventType, Consumer<E> handler) {
        handlers.computeIfAbsent(eventType, k -> new CopyOnWriteArrayList<>()).add((Consumer<?>) handler);
    }

    @SuppressWarnings("unchecked")
    public <E extends PipelineEvent> void publish(E event) {
        List<Consumer<?>> eh = handlers.get(event.getClass());
        if (eh != null) for (Consumer<?> h : eh) { try { ((Consumer<E>) h).accept(event); } catch (Exception e) { log.error("Handler error: {}", e.getMessage()); }}
        List<Consumer<?>> bh = handlers.get(PipelineEvent.class);
        if (bh != null) for (Consumer<?> h : bh) { try { ((Consumer<PipelineEvent>) h).accept(event); } catch (Exception e) { log.error("Handler error: {}", e.getMessage()); }}
    }

    public void clear() { handlers.clear(); }

    public sealed interface PipelineEvent permits StageStarted, StageCompleted, StageFailed, PipelineCompleted, TokenUsageUpdated {
        Instant at();
        String contextId();
    }
    public static record StageStarted(String stageName, String contextId, Instant at) implements PipelineEvent {}
    public static record StageCompleted(String stageName, String contextId, long durationMs, Instant at) implements PipelineEvent {}
    public static record StageFailed(String stageName, String contextId, String errorMessage, Instant at) implements PipelineEvent {}
    public static record PipelineCompleted(String contextId, boolean success, long totalDurationMs, Instant at) implements PipelineEvent {}
    public static record TokenUsageUpdated(String contextId, int total, int used, int remaining, Instant at) implements PipelineEvent {}
}
