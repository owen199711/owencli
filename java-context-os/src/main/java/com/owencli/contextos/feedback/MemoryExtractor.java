package com.owencli.contextos.feedback;

import com.owencli.contextos.core.model.TaskSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Memory Extractor — extracts structured memory content from task execution.
 * Determines what information is worth persisting.
 */
public class MemoryExtractor {

    private static final Logger log = LoggerFactory.getLogger(MemoryExtractor.class);

    public ExtractedContent extract(TaskSpec task, String response, boolean success) {
        String input = task.getRawInput();
        String intent = task.getIntent().getValue();

        // Build conversation memory entry
        String conversationEntry = String.format("User: %s\nAssistant: %s", input, truncate(response, 500));

        // Build task memory entry
        String taskEntry = String.format("[%s] %s → %s", intent, truncate(input, 80), truncate(response, 120));

        // Extract key entities and concepts
        var keyConcepts = new LinkedHashMap<String, String>();
        for (var entity : task.getEntities()) {
            if (entity.getValue() != null && entity.getValue().length() >= 2) {
                keyConcepts.put(entity.getType(), entity.getValue());
            }
        }

        // Determine if this is important enough for long-term storage
        boolean isImportant = success && input.length() > 10 && !isGreeting(input);

        var extracted = new ExtractedContent();
        extracted.setConversationEntry(conversationEntry);
        extracted.setTaskEntry(taskEntry);
        extracted.setIntent(intent);
        extracted.setInput(input);
        extracted.setResponse(response);
        extracted.setSuccess(success);
        extracted.setImportant(isImportant);
        extracted.setKeyConcepts(keyConcepts);

        log.debug("MemoryExtractor: important={}, concepts={}, intent={}", isImportant, keyConcepts.size(), intent);
        return extracted;
    }

    private boolean isGreeting(String input) {
        String trimmed = input.trim().toLowerCase();
        return trimmed.length() <= 10 && (
                trimmed.matches("^(hi|hello|hey|你好|嗨|早上好|下午好|晚上好|good morning|good afternoon|good evening|thanks|thank you|谢谢|bye|再见|ok|okay|好的|嗯|yes|no|是|不是|test|测试)\\s*$")
        );
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) : s;
    }

    public static class ExtractedContent {
        private String conversationEntry;
        private String taskEntry;
        private String intent;
        private String input;
        private String response;
        private boolean success;
        private boolean important;
        private Map<String, String> keyConcepts = new LinkedHashMap<>();

        public String getConversationEntry() { return conversationEntry; }
        public void setConversationEntry(String conversationEntry) { this.conversationEntry = conversationEntry; }
        public String getTaskEntry() { return taskEntry; }
        public void setTaskEntry(String taskEntry) { this.taskEntry = taskEntry; }
        public String getIntent() { return intent; }
        public void setIntent(String intent) { this.intent = intent; }
        public String getInput() { return input; }
        public void setInput(String input) { this.input = input; }
        public String getResponse() { return response; }
        public void setResponse(String response) { this.response = response; }
        public boolean isSuccess() { return success; }
        public void setSuccess(boolean success) { this.success = success; }
        public boolean isImportant() { return important; }
        public void setImportant(boolean important) { this.important = important; }
        public Map<String, String> getKeyConcepts() { return keyConcepts; }
        public void setKeyConcepts(Map<String, String> keyConcepts) { this.keyConcepts = keyConcepts; }
    }
}
