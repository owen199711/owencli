package com.owencli.contextos.memory;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.owencli.contextos.core.model.FactRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Instant;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Fact Memory — KV store with versioning for structured user facts.
 * <p>
 * Unlike append-only memory, Fact Memory preserves the timeline
 * so the agent always reads the current_value, not the history.
 * <p>
 * Storage: SQLite table "facts" with columns:
 *   id, type, current_value, history(JSON), confidence, status, source, created_at, updated_at
 */
public class FactMemory {

    private static final Logger log = LoggerFactory.getLogger(FactMemory.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final SQLiteStore store;
    private final String userId;

    public FactMemory(SQLiteStore store, String userId) {
        this.store = store;
        this.userId = userId;
        ensureTable();
        log.info("FactMemory initialized");
    }

    private void ensureTable() {
        // Facts are stored in the same memories table with type="fact"
        // This reuses the existing SQLiteStore infrastructure
    }

    /**
     * Set a fact. If it already exists (same type), update it with versioning.
     * If it doesn't exist, create a new entry.
     */
    public CompletableFuture<FactRecord> setFact(String type, String value, double confidence, String source) {
        return getFact(type).thenCompose(existing -> {
            if (existing.isPresent()) {
                // Update existing fact with versioning
                FactRecord record = existing.get();
                record.update(value, confidence, source);
                return saveFactRecord(record).thenApply(v -> record);
            } else {
                // Create new fact
                FactRecord record = new FactRecord(type, value);
                record.setConfidence(confidence);
                record.setSource(source);
                return saveFactRecord(record).thenApply(v -> record);
            }
        });
    }

    /**
     * Get the current value of a fact by type.
     */
    public CompletableFuture<Optional<FactRecord>> getFact(String type) {
        return store.queryMemories("fact", null, userId, null, null, null, 10, 0)
                .thenApply(results -> results.stream()
                        .map(this::rowToFactRecord)
                        .filter(Objects::nonNull)
                        .filter(r -> r.getType().equals(type))
                        .filter(FactRecord::isActive)
                        .max(Comparator.comparing(FactRecord::getUpdatedAt)));
    }

    /**
     * Get all active facts.
     */
    public CompletableFuture<List<FactRecord>> getAllFacts() {
        return store.queryMemories("fact", null, userId, null, null, null, 200, 0)
                .thenApply(results -> results.stream()
                        .map(this::rowToFactRecord)
                        .filter(Objects::nonNull)
                        .filter(FactRecord::isActive)
                        .sorted(Comparator.comparing(FactRecord::getType))
                        .collect(Collectors.toList()));
    }

    /**
     * Get fact history for a given type.
     */
    public CompletableFuture<List<String>> getFactHistory(String type) {
        return getFact(type).thenApply(opt ->
                opt.map(FactRecord::getHistory).orElse(List.of()));
    }

    /**
     * Retrieve facts relevant to a query (for context building).
     * <p>
     * Only facts whose type or value matches the query keywords are returned.
     * The unconditional "user.*" catch-all has been removed — facts must now
     * pass a keyword relevance check to avoid injecting irrelevant personal
     * data (e.g. user.name=张三) into unrelated tasks like "写 K8s Deployment".
     */
    public CompletableFuture<List<FactRecord>> retrieve(String query, int topK) {
        String q = query.toLowerCase();
        return getAllFacts().thenApply(facts -> {
            var scored = facts.stream()
                    .filter(f -> f.getType().toLowerCase().contains(q)
                            || f.getCurrentValue().toLowerCase().contains(q))
                    .map(f -> {
                        // Compute keyword overlap score for ranking
                        double score = computeKeywordOverlap(q, f);
                        // Use the higher of keyword overlap or stored confidence
                        // as the effective relevance signal
                        return new AbstractMap.SimpleEntry<>(f, score);
                    })
                    .sorted(Map.Entry.<FactRecord, Double>comparingByValue().reversed())
                    .limit(topK)
                    .map(Map.Entry::getKey)
                    .collect(Collectors.toList());
            log.debug("FactMemory.retrieve: query='{}', matched={}/{}", q, scored.size(), facts.size());
            return scored;
        });
    }

    /**
     * Compute keyword overlap between the query and a fact's type + value.
     * Returns a value in [0, 1] where 1.0 means the query fully matches.
     */
    private double computeKeywordOverlap(String query, FactRecord fact) {
        if (query == null || query.isBlank()) return 0.0;
        String text = (fact.getType() + " " + fact.getCurrentValue()).toLowerCase();
        String[] queryTokens = query.trim().split("\\s+");
        if (queryTokens.length == 0) return 0.0;
        long matchCount = java.util.Arrays.stream(queryTokens)
                .filter(token -> token.length() >= 2 && text.contains(token))
                .count();
        // Base confidence + keyword bonus, capped at 1.0
        return Math.min(1.0, fact.getConfidence() * 0.5 + (double) matchCount / queryTokens.length * 0.5);
    }

    /**
     * Save a fact record to the store.
     */
    private CompletableFuture<Void> saveFactRecord(FactRecord record) {
        try {
            String memId = record.getId();
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("fact_type", record.getType());
            metadata.put("current_value", record.getCurrentValue());
            metadata.put("history", record.getHistory());
            metadata.put("confidence", record.getConfidence());
            metadata.put("fact_status", record.getStatus());
            metadata.put("source", record.getSource());
            metadata.put("created_at", record.getCreatedAt().toString());
            metadata.put("updated_at", record.getUpdatedAt().toString());

            String content = String.format("[Fact] %s = %s (confidence=%.2f, status=%s)",
                    record.getType(), record.getCurrentValue(), record.getConfidence(), record.getStatus());

            return store.saveMemory(memId, "fact", content, null, userId, null, metadata, null)
                    .thenAccept(id -> log.debug("Fact saved: {} = {}", record.getType(), record.getCurrentValue()));
        } catch (Exception e) {
            log.warn("Failed to save fact record: {}", e.getMessage());
            return CompletableFuture.completedFuture(null);
        }
    }

    private FactRecord rowToFactRecord(Map<String, Object> row) {
        try {
            var meta = parseMetadata(row.get("metadata"));
            if (meta == null || meta.isEmpty()) return null;

            var record = new FactRecord();
            record.setId((String) row.get("id"));
            record.setType((String) meta.getOrDefault("fact_type", "unknown"));
            record.setCurrentValue((String) meta.getOrDefault("current_value", ""));
            record.setHistory(parseStringList(meta.get("history")));
            record.setConfidence(toDouble(meta.getOrDefault("confidence", 0.8)));
            record.setStatus((String) meta.getOrDefault("fact_status", "ACTIVE"));
            record.setSource((String) meta.getOrDefault("source", ""));
            try {
                record.setCreatedAt(Instant.parse((String) meta.getOrDefault("created_at", Instant.now().toString())));
                record.setUpdatedAt(Instant.parse((String) meta.getOrDefault("updated_at", Instant.now().toString())));
            } catch (Exception e) {
                record.setCreatedAt(Instant.now());
                record.setUpdatedAt(Instant.now());
            }
            return record;
        } catch (Exception e) {
            log.warn("Failed to parse fact record: {}", e.getMessage());
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    private List<String> parseStringList(Object obj) {
        if (obj instanceof List<?> list) {
            return list.stream().map(Object::toString).collect(Collectors.toList());
        }
        return new ArrayList<>();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseMetadata(Object metadata) {
        if (metadata instanceof Map m) return (Map<String, Object>) m;
        if (metadata instanceof String s) {
            try { return MAPPER.readValue(s, new TypeReference<>() {}); }
            catch (Exception e) { return Map.of(); }
        }
        return Map.of();
    }

    private double toDouble(Object obj) {
        if (obj instanceof Number n) return n.doubleValue();
        try { return Double.parseDouble(obj.toString()); }
        catch (Exception e) { return 0.0; }
    }

    /**
     * Get summarized output for all facts as context.
     */
    public CompletableFuture<String> getFactsSummary() {
        return getAllFacts().thenApply(facts -> {
            if (facts.isEmpty()) return "";
            var sb = new StringBuilder("Known facts about user:\n");
            for (var f : facts) {
                sb.append("- ").append(f.getType()).append(": ")
                        .append(f.getCurrentValue())
                        .append(" (confidence=").append(String.format("%.2f", f.getConfidence()))
                        .append(")\n");
            }
            return sb.toString();
        });
    }
}
