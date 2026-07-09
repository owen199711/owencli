package com.owencli.contextos.pipeline.middleware;

import com.owencli.contextos.pipeline.PipelineContext;
import com.owencli.contextos.pipeline.PipelineMiddleware;
import com.owencli.contextos.reflection.ReflectionEngine;
import java.util.concurrent.CompletableFuture;

public class ReflectMiddleware implements PipelineMiddleware {
    private final ReflectionEngine r;
    public ReflectMiddleware(ReflectionEngine re) { this.r = re; }
    public String name() { return "reflect"; }
    public int order() { return 800; }
    public CompletableFuture<Void> execute(PipelineContext ctx) {
        return r.reflect(ctx.taskSpec(), ctx.llmResponse(), ctx.metrics().isSuccess(),
            ctx.metrics().isSuccess() ? null : "failure", ctx.userId()).thenAccept(x -> {});
    }
}
