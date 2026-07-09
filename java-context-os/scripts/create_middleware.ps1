$dir = "d:\code\owencli\java-context-os\src\main\java\com\owencli\contextos\pipeline\middleware"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

function New-JavaFile {
    param($Name, $Body)
    Set-Content -Path "$dir\$Name" -Value $Body -Encoding UTF8
    Write-Host "  Created $Name"
}

New-JavaFile "IntentMiddleware.java" @"
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
"@

New-JavaFile "PolicyMiddleware.java" @"
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
"@

New-JavaFile "BuildMiddleware.java" @"
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
"@

New-JavaFile "OptimizeMiddleware.java" @"
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
"@

New-JavaFile "PackageMiddleware.java" @"
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
"@

New-JavaFile "LLMMiddleware.java" @"
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
"@

New-JavaFile "FeedbackMiddleware.java" @"
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
"@

New-JavaFile "ReflectMiddleware.java" @"
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
"@

Write-Host "All 8 middleware files created successfully"
