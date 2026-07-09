package com.owencli.contextos.pipeline.middleware;

import com.owencli.contextos.core.base.BaseLLMClient;
import com.owencli.contextos.pipeline.PipelineContext;
import com.owencli.contextos.pipeline.PipelineMiddleware;
import java.util.concurrent.CompletableFuture;

public class LLMMiddleware implements PipelineMiddleware {
    private final BaseLLMClient c;
    public LLMMiddleware(BaseLLMClient cl) { this.c = cl; }
    public String name() { return "llm"; }
    public int order() { return 600; }
    public CompletableFuture<Void> execute(PipelineContext ctx) {
        return c.complete(ctx.packagedContext().getRawPrompt())
            .thenAccept(r -> ctx.setLlmResponse(String.valueOf(r)));
    }
}
