package com.owencli.contextos.intent;

import com.owencli.contextos.core.model.Entity;
import com.owencli.contextos.core.model.KnowledgeRequirement;
import com.owencli.contextos.core.model.ToolRequirement;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Entity and parameter extractor.
 * Extracts named entities, tool requirements, and knowledge requirements from user input.
 */
public class EntityExtractor {

    private static final Logger log = LoggerFactory.getLogger(EntityExtractor.class);

    private static final List<ToolPattern> TOOL_PATTERNS = List.of(
            new ToolPattern("kubectl", List.of("kubectl", "k8s", "kubernetes", "集群", "cluster", "pod"), "readonly"),
            new ToolPattern("git", List.of("git", "commit", "push", "branch", "仓库"), "write"),
            new ToolPattern("npm", List.of("npm", "node", "package", "依赖"), "readonly"),
            new ToolPattern("pip", List.of("pip", "python", "requirements"), "readonly"),
            new ToolPattern("docker", List.of("docker", "container", "镜像"), "readonly"),
            new ToolPattern("sql", List.of("sql", "database", "数据库", "mysql", "postgres"), "readonly")
    );

    private static final List<DomainPattern> DOMAIN_PATTERNS = List.of(
            new DomainPattern("kubernetes", List.of("k8s", "kubernetes", "集群", "pod", "container")),
            new DomainPattern("python", List.of("python", "flask", "fastapi", "django")),
            new DomainPattern("javascript", List.of("javascript", "js", "react", "vue", "node", "typescript")),
            new DomainPattern("database", List.of("sql", "database", "数据库", "mysql", "postgres", "redis")),
            new DomainPattern("devops", List.of("devops", "ci/cd", "jenkins", "github action", "deploy"))
    );

    private static final Map<String, Pattern> ENTITY_PATTERNS = Map.of(
            "cluster", Pattern.compile("(?:集群|cluster)[=:：\\s]*([\\w-]+)", Pattern.CASE_INSENSITIVE),
            "namespace", Pattern.compile("(?:命名空间|namespace)[=:：\\s]*([\\w-]+)", Pattern.CASE_INSENSITIVE),
            "pod", Pattern.compile("(?:pod|容器)[=:：\\s]*([\\w-]+)", Pattern.CASE_INSENSITIVE),
            "file", Pattern.compile("(?:文件|file)[=:：\\s]*([\\w./\\\\-]+)", Pattern.CASE_INSENSITIVE),
            "branch", Pattern.compile("(?:分支|branch)[=:：\\s]*([\\w./-]+)", Pattern.CASE_INSENSITIVE)
    );

    private static final Pattern QUOTED_PATTERN = Pattern.compile("[\"'`]([\\w./\\\\-]+)[\"'`]");

    public EntityExtractor() {
        log.info("EntityExtractor initialized");
    }

    public List<Entity> extractEntities(String userInput) {
        List<Entity> entities = new ArrayList<>();

        for (Map.Entry<String, Pattern> entry : ENTITY_PATTERNS.entrySet()) {
            var matcher = entry.getValue().matcher(userInput);
            while (matcher.find()) {
                String value = matcher.group(1).trim();
                entities.add(new Entity(entry.getKey(), value));
                log.debug("Extracted entity: type={}, value={}", entry.getKey(), value);
            }
        }

        extractGenericEntities(userInput, entities);
        return entities;
    }

    public List<ToolRequirement> extractToolRequirements(String userInput) {
        List<ToolRequirement> tools = new ArrayList<>();
        String inputLower = userInput.toLowerCase();

        for (ToolPattern tp : TOOL_PATTERNS) {
            if (tp.keywords.stream().anyMatch(inputLower::contains)) {
                tools.add(new ToolRequirement(tp.name, false, tp.permission));
                log.debug("Detected tool requirement: {} (permission={})", tp.name, tp.permission);
            }
        }
        return tools;
    }

    public List<KnowledgeRequirement> extractKnowledgeRequirements(String userInput) {
        List<KnowledgeRequirement> requirements = new ArrayList<>();
        String inputLower = userInput.toLowerCase();

        for (DomainPattern dp : DOMAIN_PATTERNS) {
            if (dp.keywords.stream().anyMatch(inputLower::contains)) {
                requirements.add(new KnowledgeRequirement(dp.domain, userInput.substring(0, Math.min(200, userInput.length())), 5));
                log.debug("Detected knowledge requirement: domain={}", dp.domain);
            }
        }
        return requirements;
    }

    private static void extractGenericEntities(String userInput, List<Entity> entities) {
        var matcher = QUOTED_PATTERN.matcher(userInput);
        while (matcher.find()) {
            String value = matcher.group(1).trim();
            if (entities.stream().noneMatch(e -> e.getValue().equals(value))) {
                entities.add(new Entity("reference", value));
                log.debug("Extracted generic entity: reference={}", value);
            }
        }
    }

    private record ToolPattern(String name, List<String> keywords, String permission) {}
    private record DomainPattern(String domain, List<String> keywords) {}
}
