package com.owencli.contextos.pipeline.middleware;

import com.owencli.contextos.packager.ContextPackager;
import com.owencli.contextos.pipeline.PipelineContext;
import com.owencli.contextos.pipeline.PipelineMiddleware;
import java.util.concurrent.CompletableFuture;

public class PackageMiddleware implements PipelineMiddleware {
    private final ContextPackager p;
    public PackageMiddleware(ContextPackager cp) { this.p = cp; }
    public String name() { return "package"; }
    public int order() { return 500; }
    public CompletableFuture<Void> execute(PipelineContext ctx) {
        ctx.setPackagedContext(p.pack(ctx.optimizedContext(), ctx.provider()));
        return CompletableFuture.completedFuture(null);
    }
}
