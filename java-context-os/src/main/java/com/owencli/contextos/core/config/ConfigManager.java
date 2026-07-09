package main.java.com.owencli.contextos.core.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import com.owencli.contextos.core.config.model.AppConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * ConfigManager — 分层配置管理器，支持 mtime 热加载。
 * <p>
 * 参考 DeerFlow AppConfig.from_file() + mtime 检测设计。
 * <p>
 * 使用方式:
 * <pre>
 * var cm = new ConfigManager("config.yaml");
 * cm.startWatching();         // 每 30s 检测 mtime
 * AppConfig cfg = cm.get();   // 总是返回最新配置
 * cm.stopWatching();
 * </pre>
 */
public class ConfigManager implements AutoCloseable {

    private static final Logger log = LoggerFactory.getLogger(ConfigManager.class);
    private static final Pattern ENV_VAR_PATTERN = Pattern.compile("\\$\\{([^}:]+)(?::([^}]*))?\\}");

    private final ObjectMapper mapper;
    private final Path configPath;
    private final ScheduledExecutorService scheduler;

    private volatile AppConfig currentConfig;
    private volatile long lastModified;

    public ConfigManager(String configPath) {
        this.mapper = new ObjectMapper(new YAMLFactory());
        this.configPath = Paths.get(configPath != null ? configPath : "config.yaml");
        this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "config-watcher");
            t.setDaemon(true);
            return t;
        });
        reload();
    }

    /** 获取当前配置。 */
    public AppConfig get() {
        return currentConfig;
    }

    /** 检查配置文件是否有更新。 */
    public boolean checkForUpdate() {
        File file = configPath.toFile();
        if (!file.exists()) return false;
        long lm = file.lastModified();
        if (lm > lastModified) {
            reload();
            return true;
        }
        return false;
    }

    /** 开始定时检测（每 30s）。 */
    public void startWatching() {
        scheduler.scheduleAtFixedRate(() -> {
            try {
                if (checkForUpdate()) {
                    log.info("Config hot-reloaded: {}", configPath);
                }
            } catch (Exception e) {
                log.warn("Config watch error: {}", e.getMessage());
            }
        }, 30, 30, TimeUnit.SECONDS);
        log.info("ConfigWatcher started: watching {} every 30s", configPath);
    }

    /** 停止检测。 */
    public void stopWatching() {
        scheduler.shutdown();
    }

    /** 重新加载配置。 */
    public synchronized void reload() {
        File file = configPath.toFile();
        if (!file.exists()) {
            log.warn("Config file not found: {}, using defaults", configPath);
            currentConfig = new AppConfig();
            currentConfig.setLoadedAt(System.currentTimeMillis());
            return;
        }
        try {
            String raw = Files.readString(configPath, StandardCharsets.UTF_8);
            String resolved = resolveEnvVars(raw);
            AppConfig cfg = mapper.readValue(resolved, AppConfig.class);
            cfg.setLoadedAt(System.currentTimeMillis());
            this.currentConfig = cfg;
            this.lastModified = file.lastModified();
            log.info("Config loaded: {} ({} bytes)", configPath, raw.length());
        } catch (Exception e) {
            log.error("Failed to load config: {}", e.getMessage(), e);
        }
    }

    /** 替换 ${VAR:default} 环境变量。 */
    static String resolveEnvVars(String input) {
        Matcher m = ENV_VAR_PATTERN.matcher(input);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            String var = m.group(1);
            String def = m.group(2);
            String val = System.getenv(var);
            if (val == null) val = System.getProperty(var);
            if (val == null) val = def;
            m.appendReplacement(sb, Matcher.quoteReplacement(val != null ? val : ""));
        }
        m.appendTail(sb);
        return sb.toString();
    }

    @Override
    public void close() {
        stopWatching();
    }
}
