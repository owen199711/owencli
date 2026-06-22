package com.owencli.contextos.intent;

import com.owencli.contextos.core.model.Constraint;
import com.owencli.contextos.core.model.TaskSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;

/**
 * TaskSpec parser.
 * Coordinates IntentClassifier and EntityExtractor to produce a TaskSpec.
 */
public class TaskParser {

    private static final Logger log = LoggerFactory.getLogger(TaskParser.class);

    private final IntentClassifier classifier;
    private final EntityExtractor extractor;

    public TaskParser(IntentClassifier classifier, EntityExtractor extractor) {
        this.classifier = classifier;
        this.extractor = extractor;
        log.info("TaskParser initialized");
    }

    /**
     * Parse user input into a structured TaskSpec.
     */
    public CompletableFuture<TaskSpec> parse(String userInput) {
        log.info("Parsing user input: \"{}\"", userInput.substring(0, Math.min(100, userInput.length())));

        return classifier.classify(userInput).thenApply(result -> {
            log.debug("Classification complete: intent={}, goal={}, confidence={}",
                    result.intent().getValue(), result.goal().getValue(), result.confidence());

            // Extract entities, tools, knowledge requirements
            var entities = extractor.extractEntities(userInput);
            var tools = extractor.extractToolRequirements(userInput);
            var knowledge = extractor.extractKnowledgeRequirements(userInput);

            var taskSpec = new TaskSpec();
            taskSpec.setRawInput(userInput);
            taskSpec.setIntent(result.intent());
            taskSpec.setGoal(result.goal());
            taskSpec.setEntities(entities);
            taskSpec.setConstraint(new Constraint());
            taskSpec.setToolRequirements(tools);
            taskSpec.setKnowledgeRequirements(knowledge);
            taskSpec.setConfidence(result.confidence());

            log.info("Parsed TaskSpec: id={}, intent={}, goal={}, confidence={}, entities={}, tools={}, knowledge={}",
                    taskSpec.getId(), result.intent().getValue(), result.goal().getValue(),
                    result.confidence(), entities.size(), tools.size(), knowledge.size());

            return taskSpec;
        });
    }
}
