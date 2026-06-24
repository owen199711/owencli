package com.owencli.contextos.core.model;

import java.util.ArrayList;
import java.util.List;

/**
 * Episode Info — structured info about a completed task episode.
 * <p>
 * Used by BehaviorDetector to analyze patterns across episodes.
 */
public class EpisodeInfo {

    private String episodeId;
    private String intent;
    private String action;
    private String userInput;
    private String response;
    private boolean success;
    private String rootCause;     // from Reflection (if failure)
    private String lesson;        // from Reflection
    private List<String> toolsUsed = new ArrayList<>();

    public EpisodeInfo() {}

    public String getEpisodeId() { return episodeId; }
    public void setEpisodeId(String episodeId) { this.episodeId = episodeId; }
    public String getIntent() { return intent; }
    public void setIntent(String intent) { this.intent = intent; }
    public String getAction() { return action; }
    public void setAction(String action) { this.action = action; }
    public String getUserInput() { return userInput; }
    public void setUserInput(String userInput) { this.userInput = userInput; }
    public String getResponse() { return response; }
    public void setResponse(String response) { this.response = response; }
    public boolean isSuccess() { return success; }
    public void setSuccess(boolean success) { this.success = success; }
    public String getRootCause() { return rootCause; }
    public void setRootCause(String rootCause) { this.rootCause = rootCause; }
    public String getLesson() { return lesson; }
    public void setLesson(String lesson) { this.lesson = lesson; }
    public List<String> getToolsUsed() { return toolsUsed; }
    public void setToolsUsed(List<String> toolsUsed) { this.toolsUsed = toolsUsed; }
}
