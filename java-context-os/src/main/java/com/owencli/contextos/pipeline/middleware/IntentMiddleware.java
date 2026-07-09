package com.owencli.contextos.pipeline.middleware;

import com.owencli.contextos.pipeline.PipelineContext;
import com.owencli.contextos.pipeline.PipelineMiddleware;
import com.owencli.contextos.intent.TaskParser;
import java.util.concurrent.CompletableFuture;

public class IntentMiddleware implements PipelineMiddleware {
    private final TaskParser tp;
    public IntentMiddleware(TaskParser t) { this.tp = t; }
    public String name() { return "intent"; }
    public int order() { return 100; }
    public CompletableFuture<Void> execute(PipelineContext ctx) {
        return tp.parse(ctx.userInput()).thenAccept(ctx::setTaskSpec);
    }
}
