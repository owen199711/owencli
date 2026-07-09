package com.owencli.contextos.pipeline.middleware;

import com.owencli.contextos.optimizer.ContextOptimizer;
import com.owencli.contextos.pipeline.PipelineContext;
import com.owencli.contextos.pipeline.PipelineMiddleware;
import java.util.concurrent.CompletableFuture;

public class OptimizeMiddleware implements PipelineMiddleware {
    private final ContextOptimizer o;
    public OptimizeMiddleware(ContextOptimizer co) { this.o = co; }
    public String name() { return "optimize"; }
    public int order() { return 400; }
    public CompletableFuture<Void> execute(PipelineContext ctx) {
        return o.optimize(ctx.unifiedContext(), ctx.taskSpec()).thenAccept(ctx::setOptimizedContext);
    }
}
