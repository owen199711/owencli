package com.owencli.contextos.store;

import com.owencli.contextos.core.model.*;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 存储会话 — 封装一次数据库连接内的所有操作。
 * <p>
 * 参考 DeerFlow 的 Store + Checkpointer 抽象，
 * 将 Context-OS 的 Memory、Episode、Concept、Fact 统一管理。
 */
public interface StoreSession extends AutoCloseable {

    // ── Memory (memories 表) ──
    CompletableFuture<String> saveMemory(String id, String type, String content,
                                          String sessionId, String userId,
                                          List<Double> embedding, Map<String, Object> metadata,
                                          Integer ttlSeconds);
    CompletableFuture<Void> updateMemoryContent(String id, String content);
    CompletableFuture<Optional<MemoryItem>> loadMemory(String id);
    CompletableFuture<List<MemoryItem>> queryMemories(String type, String sessionId, String userId);
    CompletableFuture<List<MemoryItem>> searchMemories(String userId, String query, int limit);
    CompletableFuture<Void> deleteMemory(String id);
    CompletableFuture<Void> incrementAccessCount(String id);
    CompletableFuture<Void> cleanupExpired();

    // ── Episode (episodes 表) ──
    CompletableFuture<String> saveEpisode(String id, String scene, String action, String result,
                                           String feedback, List<String> tags, String userId);
    CompletableFuture<List<Episode>> queryEpisodes(String userId, int limit);
    CompletableFuture<List<Episode>> queryEpisodesByTag(String userId, String tag, int limit);

    // ── Concept / Knowledge Graph ──
    CompletableFuture<String> saveConcept(Concept concept);
    CompletableFuture<Optional<Concept>> loadConcept(String id);
    CompletableFuture<List<Concept>> searchConcepts(String keyword, int limit);
    CompletableFuture<String> saveRelation(ConceptRelation relation);
    CompletableFuture<List<ConceptRelation>> getRelations(String conceptId);

    // ── Fact (FactMemory) ──
    CompletableFuture<String> saveFact(FactRecord fact);
    CompletableFuture<Optional<FactRecord>> loadFact(String id);
    CompletableFuture<List<FactRecord>> queryFacts(String userId, int limit);

    // ── 生命周期 ──
    CompletableFuture<Void> flush();
    void close();
}
