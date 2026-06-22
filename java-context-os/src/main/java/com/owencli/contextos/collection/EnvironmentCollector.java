package com.owencli.contextos.collection;

import com.owencli.contextos.core.model.EnvironmentContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Environment collector - collects system environment context.
 */
public class EnvironmentCollector {

    private static final Logger log = LoggerFactory.getLogger(EnvironmentCollector.class);

    private static final List<String> ALLOWED_ENV_PREFIXES = List.of(
            "PATH", "HOME", "USER", "SHELL", "TERM", "LANG", "LC_", "LOG_LEVEL"
    );

    private final Map<String, String> mcpServers;

    public EnvironmentCollector() {
        this(Map.of());
    }

    public EnvironmentCollector(Map<String, String> mcpServers) {
        this.mcpServers = mcpServers;
        log.info("EnvironmentCollector initialized (mcp_servers={})", mcpServers.size());
    }

    public CompletableFuture<EnvironmentContext> collect() {
        log.debug("Collecting environment context...");

        var context = new EnvironmentContext();
        context.setOs(System.getProperty("os.name"));

        context.setWorkingDirectory(Paths.get("").toAbsolutePath().toString());

        var runtime = new HashMap<String, Object>();
        runtime.put("java_version", System.getProperty("java.version"));
        runtime.put("java_vendor", System.getProperty("java.vendor"));
        runtime.put("os_arch", System.getProperty("os.arch"));
        runtime.put("os_version", System.getProperty("os.version"));
        runtime.put("user_name", System.getProperty("user.name"));
        context.setRuntime(runtime);

        context.setGitBranch(getGitBranch());
        context.setGitRepo(getGitRemote());
        context.setEnvVars(collectEnvVars());
        context.setMcpServers(new HashMap<>(mcpServers));

        log.info("Environment collected: os={}, git_branch={}, git_repo={}",
                context.getOs(), context.getGitBranch(), context.getGitRepo());
        return CompletableFuture.completedFuture(context);
    }

    private static String getGitBranch() {
        try {
            var process = new ProcessBuilder("git", "rev-parse", "--abbrev-ref", "HEAD")
                    .start();
            try (var reader = new BufferedReader(new InputStreamReader(process.getInputStream()))) {
                String line = reader.readLine();
                if (line != null && !line.isEmpty()) {
                    return line.trim();
                }
            }
        } catch (Exception e) {
            log.debug("Failed to get git branch: {}", e.getMessage());
        }
        return null;
    }

    private static String getGitRemote() {
        try {
            var process = new ProcessBuilder("git", "remote", "get-url", "origin")
                    .start();
            try (var reader = new BufferedReader(new InputStreamReader(process.getInputStream()))) {
                String line = reader.readLine();
                if (line != null && !line.isEmpty()) {
                    return line.trim();
                }
            }
        } catch (Exception e) {
            log.debug("Failed to get git remote: {}", e.getMessage());
        }
        return null;
    }

    private static Map<String, String> collectEnvVars() {
        Map<String, String> vars = new HashMap<>();
        for (Map.Entry<String, String> entry : System.getenv().entrySet()) {
            for (String prefix : ALLOWED_ENV_PREFIXES) {
                if (entry.getKey().startsWith(prefix)) {
                    vars.put(entry.getKey(), entry.getValue());
                    break;
                }
            }
        }
        log.debug("Collected {} environment variables", vars.size());
        return vars;
    }
}
