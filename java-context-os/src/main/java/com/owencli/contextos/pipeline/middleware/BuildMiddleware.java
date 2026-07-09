package com.owencli.contextos.pipeline.middleware;

import com.owencli.contextos.builder.ContextBuilder;
import com.owencli.contextos.pipeline.PipelineContext;
import com.owencli.contextos.pipeline.PipelineMiddleware;
import java.util.concurrent.CompletableFuture;

public class BuildMiddleware implements PipelineMiddleware {
    private final ContextBuilder b;
    public BuildMiddleware(ContextBuilder cb) { this.b = cb; }
    public String name() { return "build"; }
    public int order() { return 300; }
    public CompletableFuture<Void> execute(PipelineContext ctx) {
        return b.build(ctx.taskSpec()).thenAccept(ctx::setUnifiedContext);
    }
}
