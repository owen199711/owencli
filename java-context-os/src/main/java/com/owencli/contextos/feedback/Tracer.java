package com.owencli.contextos.feedback;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.owencli.contextos.core.model.Trace;
import com.owencli.contextos.core.model.TraceStep;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.time.Instant;
import java.util.UUID;

public class Tracer {
    private static final Logger log = LoggerFactory.getLogger(Tracer.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final File storageDir;
    private Trace current;
    private long stepTimer;

    public Tracer() { this("./data/traces"); }
    public Tracer(String storageDir) {
        this.storageDir = new File(storageDir);
        this.storageDir.mkdirs();
    }

    public String start(String taskId, String rawInput) {
        current = new Trace();
        current.setTaskId(taskId);
        current.setRawInput(rawInput);
        current.setCreatedAt(Instant.now());
        current.setId(UUID.randomUUID().toString().replace("-", ""));
        return current.getId();
    }

    public TraceStep stepBegin(String stepName) {
        stepTimer = System.currentTimeMillis();
        return new TraceStep(stepName);
    }

    public void stepEnd(TraceStep step, String inputText, String outputText) {
        step.setDurationMs(System.currentTimeMillis() - stepTimer);
        step.setInputPreview(truncate(inputText, 200));
        step.setOutputPreview(truncate(outputText, 200));
        if (current != null) {
            current.getSteps().add(step);
            current.setTotalLatencyMs(current.getTotalLatencyMs() + step.getDurationMs());
        }
    }

    public void finish(boolean success) {
        if (current == null) return;
        current.setSuccess(success);
        try {
            var ts = Instant.now().toString().replace(":", "-").substring(0, 19);
            MAPPER.writerWithDefaultPrettyPrinter().writeValue(new File(storageDir, "trace_" + current.getId() + "_" + ts + ".json"), current);
        } catch (Exception e) { log.error("Failed to save trace: {}", e.getMessage()); }
        current = null;
    }

    private static String truncate(String s, int max) { return s != null && s.length() > max ? s.substring(0, max) : s; }
}
