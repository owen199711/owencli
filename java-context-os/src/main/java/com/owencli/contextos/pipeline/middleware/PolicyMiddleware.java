package com.owencli.contextos.pipeline.middleware;

import com.owencli.contextos.pipeline.PipelineContext;
import com.owencli.contextos.pipeline.PipelineMiddleware;
import com.owencli.contextos.policy.ContextPolicy;
import java.util.concurrent.CompletableFuture;

public class PolicyMiddleware implements PipelineMiddleware {
    private final ContextPolicy cp;
    public PolicyMiddleware(ContextPolicy c) { this.cp = c; }
    public String name() { return "policy"; }
    public int order() { return 200; }
    public CompletableFuture<Void> execute(PipelineContext ctx) {
        ctx.setPolicyDirective(cp.evaluate(ctx.taskSpec()));
        return CompletableFuture.completedFuture(null);
    }
}
