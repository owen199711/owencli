package com.owencli.contextos.pipeline.middleware;

import com.owencli.contextos.feedback.MemoryUpdater;
import com.owencli.contextos.feedback.QualityEvaluator;
import com.owencli.contextos.pipeline.PipelineContext;
import com.owencli.contextos.pipeline.PipelineMiddleware;
import java.util.concurrent.CompletableFuture;

public class FeedbackMiddleware implements PipelineMiddleware {
    private final QualityEvaluator e;
    private final MemoryUpdater m;
    public FeedbackMiddleware(QualityEvaluator ev, MemoryUpdater mu) { this.e = ev; this.m = mu; }
    public String name() { return "feedback"; }
    public int order() { return 700; }
    public CompletableFuture<Void> execute(PipelineContext ctx) {
        var pc = ctx.packagedContext();
        int tok = ctx.optimizedContext().getTokenUsage().getUsed();
        if (tok == 0) tok = pc.getRawPrompt().length() / 4;
        return e.evaluate(pc, ctx.llmResponse(), 0, tok)
            .thenCompose(me -> { ctx.setMetrics(me); return m.updateFromTask(ctx.taskSpec(), ctx.llmResponse(), me, ctx.userId()); })
            .thenAccept(ctx::setMemoryUpdateResult);
    }
}
