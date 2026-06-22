package com.owencli.contextos.core.model;

import java.util.HashMap;
import java.util.Map;

public class EnvironmentContext {
    private String os;
    private String workingDirectory;
    private String gitBranch;
    private String gitRepo;
    private Map<String, Object> runtime = new HashMap<>();
    private Map<String, String> mcpServers = new HashMap<>();
    private Map<String, String> envVars = new HashMap<>();

    public String getOs() { return os; }
    public void setOs(String os) { this.os = os; }
    public String getWorkingDirectory() { return workingDirectory; }
    public void setWorkingDirectory(String workingDirectory) { this.workingDirectory = workingDirectory; }
    public String getGitBranch() { return gitBranch; }
    public void setGitBranch(String gitBranch) { this.gitBranch = gitBranch; }
    public String getGitRepo() { return gitRepo; }
    public void setGitRepo(String gitRepo) { this.gitRepo = gitRepo; }
    public Map<String, Object> getRuntime() { return runtime; }
    public void setRuntime(Map<String, Object> runtime) { this.runtime = runtime; }
    public Map<String, String> getMcpServers() { return mcpServers; }
    public void setMcpServers(Map<String, String> mcpServers) { this.mcpServers = mcpServers; }
    public Map<String, String> getEnvVars() { return envVars; }
    public void setEnvVars(Map<String, String> envVars) { this.envVars = envVars; }
}
