package com.owencli.contextos.pipeline;

import com.owencli.contextos.core.exception.ContextOSException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

public class PipelineEngine {
    private static final Logger log = LoggerFactory.getLogger(PipelineEngine.class);
    private final List<PipelineMiddleware> middlewares;
    private final PipelineEventBus eventBus;
    private final String contextId;

    public PipelineEngine(List<PipelineMiddleware> middlewares, PipelineEventBus eventBus) {
        var sorted = new ArrayList<>(middlewares);
        sorted.sort(Comparator.comparingInt(PipelineMiddleware::order));
        this.middlewares = List.copyOf(sorted);
        this.eventBus = eventBus != null ? eventBus : new PipelineEventBus();
        this.contextId = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        log.info("PipelineEngine: {} middlewares registered", this.middlewares.size());
        for (PipelineMiddleware mw : this.middlewares)
            log.info("  MW [{:3d}] {}", mw.order(), mw.name());
    }

    public CompletableFuture<PipelineContext> execute(PipelineContext ctx) {
        long pipelineStart = System.currentTimeMillis();
        List<PipelineMiddleware> enabled = middlewares.stream()
                .filter(mw -> mw.isEnabled(ctx)).toList();
        log.info("========== PipelineEngine start: context={}, mw={}/{} ==========", contextId, enabled.size(), middlewares.size());

        CompletableFuture<Void> chain = CompletableFuture.completedFuture(null);
        for (PipelineMiddleware mw : enabled) {
            chain = chain.thenCompose(v -> {
                if (ctx.isCancelled()) return CompletableFuture.completedFuture(null);
                long t0 = System.currentTimeMillis();
                eventBus.publish(new PipelineEvent.StageStarted(mw.name(), contextId, Instant.now()));
                return mw.execute(ctx).thenAccept(r -> {
                    long dur = System.currentTimeMillis() - t0;
                    eventBus.publish(new PipelineEvent.StageCompleted(mw.name(), contextId, dur, Instant.now()));
                    log.info("MW [{}] {} done in {}ms", mw.order(), mw.name(), dur);
                }).exceptionally(e -> {
                    long dur = System.currentTimeMillis() - t0;
                    eventBus.publish(new PipelineEvent.StageFailed(mw.name(), contextId, e.getMessage(), Instant.now()));
                    throw new ContextOSException("MW [" + mw.order() + "] " + mw.name() + " failed", e);
                });
            });
        }
        return chain.thenApply(v -> {
            long total = System.currentTimeMillis() - pipelineStart;
            boolean ok = !ctx.isCancelled();
            eventBus.publish(new PipelineEvent.PipelineCompleted(contextId, ok, total, Instant.now()));
            log.info("========== PipelineEngine end: success={}, total={}ms ==========", ok, total);
            return ctx;
        });
    }
    public PipelineEventBus eventBus() { return eventBus; }
    public List<PipelineMiddleware> middlewares() { return middlewares; }
}
