package com.owencli.contextos.pipeline;
import java.util.concurrent.CompletableFuture;
public interface PipelineMiddleware {
    String name();
    int order();
    default boolean isEnabled(PipelineContext ctx) { return true; }
    CompletableFuture<Void> execute(PipelineContext ctx);
}
