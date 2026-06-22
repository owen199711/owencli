package com.owencli.contextos.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.owencli.contextos.core.exception.MemoryException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.sql.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

public class SQLiteStore {
    private static final Logger log = LoggerFactory.getLogger(SQLiteStore.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final String dbPath;
    private Connection connection;

    public SQLiteStore() { this("./data/context_os.db"); }
    public SQLiteStore(String dbPath) { this.dbPath = dbPath != null ? dbPath : "./data/context_os.db"; log.info("SQLiteStore initialized: db_path={}", this.dbPath); }

    public synchronized CompletableFuture<Void> connect() {
        return CompletableFuture.runAsync(() -> {
            try {
                if (connection != null && !connection.isClosed()) return;
                new java.io.File(dbPath).toPath().getParent().toFile().mkdirs();
                connection = DriverManager.getConnection("jdbc:sqlite:" + dbPath);
                try (var stmt = connection.createStatement()) {
                    stmt.execute("PRAGMA journal_mode=WAL");
                    stmt.execute("PRAGMA foreign_keys=ON");
                    stmt.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, type TEXT NOT NULL, content TEXT NOT NULL, embedding TEXT, session_id TEXT, user_id TEXT DEFAULT 'anonymous', timestamp TEXT NOT NULL DEFAULT (datetime('now')), access_count INTEGER DEFAULT 0, relevance_score REAL DEFAULT 0.0, metadata TEXT DEFAULT '{}', expires_at TEXT)");
                    stmt.execute("CREATE TABLE IF NOT EXISTS episodes (id TEXT PRIMARY KEY, scene TEXT NOT NULL, action TEXT NOT NULL, result TEXT NOT NULL, feedback TEXT DEFAULT '', related_files TEXT DEFAULT '[]', tags TEXT DEFAULT '[]', user_id TEXT DEFAULT 'anonymous', timestamp TEXT NOT NULL DEFAULT (datetime('now')))");
                    stmt.execute("CREATE TABLE IF NOT EXISTS concept_relations (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, target_id TEXT NOT NULL, relation_type TEXT NOT NULL, weight REAL DEFAULT 1.0, created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(source_id, target_id, relation_type))");
                    stmt.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)");
                    stmt.execute("CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id)");
                }
            } catch (SQLException e) { throw new MemoryException("SQLite connection failed: " + e.getMessage(), e); }
        });
    }

    public synchronized CompletableFuture<Void> close() {
        return CompletableFuture.runAsync(() -> { try { if (connection != null && !connection.isClosed()) { connection.close(); connection = null; } } catch (SQLException e) { log.error("Failed to close SQLite: {}", e.getMessage()); }});
    }

    private void ensureConnected() { try { if (connection == null || connection.isClosed()) throw new MemoryException("SQLite not connected"); } catch (SQLException e) { throw new MemoryException("SQLite not connected"); }}

    public CompletableFuture<String> saveMemory(String id, String type, String content, String sessionId, String userId, List<Double> embedding, Map<String, Object> metadata, Integer ttlSeconds) {
        return CompletableFuture.supplyAsync(() -> {
            try { ensureConnected();
                String expiresAt = ttlSeconds != null ? Instant.now().plusSeconds(ttlSeconds).toString() : null;
                try (var pstmt = connection.prepareStatement("INSERT INTO memories (id,type,content,embedding,session_id,user_id,metadata,expires_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET content=excluded.content, metadata=excluded.metadata, access_count=0, relevance_score=0")) {
                    pstmt.setString(1, id); pstmt.setString(2, type); pstmt.setString(3, content);
                    pstmt.setString(4, embedding != null ? MAPPER.writeValueAsString(embedding) : null);
                    pstmt.setString(5, sessionId); pstmt.setString(6, userId != null ? userId : "anonymous");
                    pstmt.setString(7, metadata != null ? MAPPER.writeValueAsString(metadata) : "{}");
                    pstmt.setString(8, expiresAt); pstmt.executeUpdate();
                } return id;
            } catch (Exception e) { throw new MemoryException("Failed to save memory", e); }
        });
    }

    public CompletableFuture<List<Map<String, Object>>> queryMemories(String type, String sessionId, String userId, String queryText, List<Double> embedding, int topK, int offset) {
        return queryMemories(type, sessionId, userId, queryText, null, embedding, topK, offset);
    }

    /**
     * Query memories with keyword-based OR matching AND optional vector similarity.
     * <p>
     * When {@code embedding} is provided (non-null, non-empty), the method:
     * <ol>
     *   <li>First fetches candidate rows using keyword OR LIKE (if keywords exist)
     *       or a broader scan (up to 200 rows)</li>
     *   <li>For rows with stored embeddings, computes cosine similarity against the query embedding</li>
     *   <li>Ranks results by similarity × 0.7 + keywordMatchRatio × 0.3 and returns top-K</li>
     * </ol>
     */
    public CompletableFuture<List<Map<String, Object>>> queryMemories(
            String type, String sessionId, String userId,
            String queryText, java.util.List<String> keywords,
            List<Double> embedding, int topK, int offset) {
        return CompletableFuture.supplyAsync(() -> {
            try { ensureConnected();
                var conditions = new ArrayList<String>();
                var params = new ArrayList<>();

                if (type != null) { conditions.add("type = ?"); params.add(type); }
                if (sessionId != null) { conditions.add("session_id = ?"); params.add(sessionId); }
                if (userId != null) { conditions.add("user_id = ?"); params.add(userId); }

                // ── 关键词 OR LIKE 匹配（初筛）──
                var keywordConditions = new ArrayList<String>();
                if (keywords != null && !keywords.isEmpty()) {
                    for (var kw : keywords) {
                        if (kw.length() >= 2) {
                            keywordConditions.add("content LIKE ?");
                            params.add("%" + kw + "%");
                        }
                    }
                }
                if (queryText != null && !queryText.isEmpty()
                        && (keywords == null || keywords.stream().noneMatch(k -> queryText.contains(k)))) {
                    keywordConditions.add("content LIKE ?");
                    params.add("%" + queryText + "%");
                }

                if (!keywordConditions.isEmpty()) {
                    conditions.add("(" + String.join(" OR ", keywordConditions) + ")");
                }

                String sql = "SELECT * FROM memories WHERE "
                        + (conditions.isEmpty() ? "1=1" : String.join(" AND ", conditions))
                        + " ORDER BY timestamp DESC, relevance_score DESC LIMIT ? OFFSET ?";
                int fetchLimit = (embedding != null && !embedding.isEmpty()) ? Math.max(topK * 8, 200) : topK;
                params.add(fetchLimit);
                params.add(offset);

                var results = new ArrayList<Map<String, Object>>();
                try (var pstmt = connection.prepareStatement(sql)) {
                    for (int i = 0; i < params.size(); i++) {
                        var val = params.get(i);
                        if (val instanceof String s) pstmt.setString(i+1, s);
                        else if (val instanceof Integer it) pstmt.setInt(i+1, it);
                    }
                    var rs = pstmt.executeQuery();
                    while (rs.next()) {
                        var map = new HashMap<String, Object>();
                        for (int i = 1; i <= rs.getMetaData().getColumnCount(); i++) {
                            map.put(rs.getMetaData().getColumnName(i), rs.getObject(i));
                        }
                        results.add(map);
                    }
                }

                // ── 向量相似度重排序 ──
                if (embedding != null && !embedding.isEmpty()) {
                    // 如果关键词初筛结果为空但确实有 embedding，回退到最近 N 条做向量排序
                    if (results.isEmpty() && !keywordConditions.isEmpty()) {
                        log.debug("Keyword match returned 0 results — falling back to recent entries for vector ranking");
                        var fallbackConditions = new ArrayList<>(conditions);
                        fallbackConditions.removeIf(c -> c.startsWith("(")); // 移除关键词条件
                        String fallbackSql = "SELECT * FROM memories WHERE "
                                + (fallbackConditions.isEmpty() ? "1=1" : String.join(" AND ", fallbackConditions))
                                + " ORDER BY timestamp DESC LIMIT ?";
                        try (var pstmt2 = connection.prepareStatement(fallbackSql)) {
                            int idx = 1;
                            if (type != null) { pstmt2.setString(idx++, type); }
                            if (sessionId != null) { pstmt2.setString(idx++, sessionId); }
                            if (userId != null) { pstmt2.setString(idx++, userId); }
                            pstmt2.setInt(idx, Math.max(topK * 4, 100));
                            var rs2 = pstmt2.executeQuery();
                            while (rs2.next()) {
                                var map = new HashMap<String, Object>();
                                for (int i = 1; i <= rs2.getMetaData().getColumnCount(); i++) {
                                    map.put(rs2.getMetaData().getColumnName(i), rs2.getObject(i));
                                }
                                results.add(map);
                            }
                        }
                    }

                    for (var row : results) {
                        var storedEmb = parseEmbedding((String) row.get("embedding"));
                        double cosSim = storedEmb != null
                                ? EmbeddingService.cosineSimilarity(embedding, storedEmb)
                                : 0.0;

                        // 关键词匹配比例
                        double kwRatio = 0.0;
                        if (keywords != null && !keywords.isEmpty()) {
                            String content = (String) row.getOrDefault("content", "");
                            long matchCount = keywords.stream()
                                    .filter(kw -> content != null && content.contains(kw))
                                    .count();
                            kwRatio = (double) matchCount / keywords.size();
                        }

                        // 综合得分: 向量 70% + 关键词 30%
                        double combinedScore = cosSim * 0.7 + kwRatio * 0.3;
                        row.put("_vector_score", combinedScore);
                        row.put("_cosine_sim", cosSim);
                    }

                    // 按综合得分降序排列，取 topK
                    results.sort((a, b) -> Double.compare(
                            (Double) b.getOrDefault("_vector_score", 0.0),
                            (Double) a.getOrDefault("_vector_score", 0.0)));
                    if (results.size() > topK) {
                        results.subList(topK, results.size()).clear();
                    }
                }

                return results;
            } catch (Exception e) { throw new MemoryException("Failed to query memories", e); }
        });
    }

    private List<Double> parseEmbedding(String json) {
        if (json == null || json.isBlank()) return null;
        try {
            return MAPPER.readValue(json, MAPPER.getTypeFactory()
                    .constructCollectionType(ArrayList.class, Double.class));
        } catch (Exception e) {
            return null;
        }
    }

    public CompletableFuture<Void> deleteMemory(String id) {
        return CompletableFuture.runAsync(() -> {
            try { ensureConnected(); try (var pstmt = connection.prepareStatement("DELETE FROM memories WHERE id = ?")) { pstmt.setString(1, id); pstmt.executeUpdate(); }} catch (SQLException e) { throw new MemoryException("Failed to delete memory", e); }
        });
    }

    public CompletableFuture<List<Map<String, Object>>> queryEpisodes(String queryText, List<String> tags, String userId, int topK) {
        return CompletableFuture.supplyAsync(() -> {
            try { ensureConnected();
                var conditions = new ArrayList<String>();
                var params = new ArrayList<>();

                if (queryText != null && !queryText.isEmpty()) {
                    var keywords = new LinkedHashSet<String>();
                    var chineseMatcher = Pattern.compile("[\\u4e00-\\u9fff]{2,}").matcher(queryText);
                    while (chineseMatcher.find()) { keywords.add(chineseMatcher.group()); }
                    for (var w : queryText.toLowerCase().split("[^a-zA-Z0-9]+")) { if (w.length() >= 3) keywords.add(w); }

                    var likeClauses = new ArrayList<String>();
                    for (var kw : keywords) {
                        if (kw.length() >= 2) {
                            likeClauses.add("(scene LIKE ? OR action LIKE ? OR result LIKE ?)");
                            params.add("%" + kw + "%"); params.add("%" + kw + "%"); params.add("%" + kw + "%");
                        }
                    }
                    if (!likeClauses.isEmpty()) conditions.add("(" + String.join(" OR ", likeClauses) + ")");
                }
                if (tags != null && !tags.isEmpty()) {
                    var tagLike = tags.stream().map(t -> "tags LIKE ?").collect(Collectors.toList());
                    conditions.add("(" + String.join(" OR ", tagLike) + ")");
                    tags.forEach(t -> params.add("%" + t + "%"));
                }
                if (userId != null && !userId.isEmpty()) { conditions.add("user_id = ?"); params.add(userId); }

                String sql = "SELECT * FROM episodes WHERE " + (conditions.isEmpty() ? "1=1" : String.join(" AND ", conditions))
                        + " ORDER BY timestamp DESC LIMIT ?";
                params.add(topK);

                var results = new ArrayList<Map<String, Object>>();
                try (var pstmt = connection.prepareStatement(sql)) {
                    for (int i = 0; i < params.size(); i++) {
                        var val = params.get(i);
                        if (val instanceof String s) pstmt.setString(i + 1, s);
                        else if (val instanceof Integer it) pstmt.setInt(i + 1, it);
                    }
                    var rs = pstmt.executeQuery();
                    while (rs.next()) {
                        var map = new HashMap<String, Object>();
                        for (int i = 1; i <= rs.getMetaData().getColumnCount(); i++) {
                            map.put(rs.getMetaData().getColumnName(i), rs.getObject(i));
                        }
                        results.add(map);
                    }
                }
                return results;
            } catch (Exception e) { throw new MemoryException("Failed to query episodes", e); }
        });
    }

    public CompletableFuture<String> saveEpisode(String scene, String action, String result, String feedback, List<String> relatedFiles, List<String> tags, String userId) {
        return CompletableFuture.supplyAsync(() -> {
            try { ensureConnected();
                String id = UUID.randomUUID().toString().replace("-", "");
                try (var pstmt = connection.prepareStatement("INSERT INTO episodes (id,scene,action,result,feedback,related_files,tags,user_id) VALUES (?,?,?,?,?,?,?,?)")) {
                    pstmt.setString(1, id); pstmt.setString(2, scene); pstmt.setString(3, action); pstmt.setString(4, result);
                    pstmt.setString(5, feedback);
                    pstmt.setString(6, relatedFiles != null ? MAPPER.writeValueAsString(relatedFiles) : "[]");
                    pstmt.setString(7, tags != null ? MAPPER.writeValueAsString(tags) : "[]");
                    pstmt.setString(8, userId); pstmt.executeUpdate();
                } return id;
            } catch (Exception e) { throw new MemoryException("Failed to save episode", e); }
        });
    }

    public CompletableFuture<String> saveConcept(String name, Map<String, Object> attributes, List<Double> embedding, double confidence, String userId) {
        return CompletableFuture.supplyAsync(() -> {
            try { ensureConnected();
                String id = UUID.randomUUID().toString().replace("-", "");
                try (var pstmt = connection.prepareStatement("INSERT OR REPLACE INTO memories (id,type,content,embedding,user_id,metadata) VALUES (?,?,?,?,?,?)")) {
                    pstmt.setString(1, id); pstmt.setString(2, "semantic"); pstmt.setString(3, name);
                    pstmt.setString(4, embedding != null ? MAPPER.writeValueAsString(embedding) : null);
                    pstmt.setString(5, userId);
                    pstmt.setString(6, attributes != null ? MAPPER.writeValueAsString(attributes) : "{}");
                    pstmt.executeUpdate();
                } return id;
            } catch (Exception e) { throw new MemoryException("Failed to save concept", e); }
        });
    }

    public CompletableFuture<String> saveRelation(String sourceName, String targetName, String relationType, double weight) {
        return CompletableFuture.supplyAsync(() -> {
            try { ensureConnected();
                // 查找 source 和 target 概念的 ID
                String sourceId = null, targetId = null;
                try (var pstmt = connection.prepareStatement("SELECT id FROM memories WHERE type='semantic' AND content = ?")) {
                    pstmt.setString(1, sourceName);
                    var rs = pstmt.executeQuery();
                    if (rs.next()) sourceId = rs.getString("id");
                }
                try (var pstmt = connection.prepareStatement("SELECT id FROM memories WHERE type='semantic' AND content = ?")) {
                    pstmt.setString(1, targetName);
                    var rs = pstmt.executeQuery();
                    if (rs.next()) targetId = rs.getString("id");
                }
                if (sourceId == null || targetId == null) {
                    log.warn("Cannot create relation: concept not found: '{}' or '{}'", sourceName, targetName);
                    return "";
                }
                String id = UUID.randomUUID().toString().replace("-", "");
                try (var pstmt = connection.prepareStatement(
                        "INSERT OR REPLACE INTO concept_relations (id,source_id,target_id,relation_type,weight) VALUES (?,?,?,?,?)")) {
                    pstmt.setString(1, id);
                    pstmt.setString(2, sourceId);
                    pstmt.setString(3, targetId);
                    pstmt.setString(4, relationType);
                    pstmt.setDouble(5, weight);
                    pstmt.executeUpdate();
                }
                log.debug("Relation saved: {} --[{}]--> {}", sourceName, relationType, targetName);
                return id;
            } catch (Exception e) {
                throw new MemoryException("Failed to save relation", e);
            }
        });
    }

    public CompletableFuture<Map<String, Object>> queryGraph(String conceptName, int depth) {
        return CompletableFuture.supplyAsync(() -> {
            try { ensureConnected();
                // 查找概念
                String startId = null;
                try (var pstmt = connection.prepareStatement("SELECT id FROM memories WHERE type='semantic' AND content = ?")) {
                    pstmt.setString(1, conceptName);
                    var rs = pstmt.executeQuery();
                    if (rs.next()) startId = rs.getString("id");
                }
                if (startId == null) return Map.of("nodes", List.of(), "edges", List.of());

                var nodeMap = new LinkedHashMap<String, Map<String, Object>>();
                var edgeList = new ArrayList<Map<String, Object>>();
                var visited = new HashSet<String>();
                var currentLevel = new HashSet<>(Set.of(startId));

                // 获取起始节点
                addConceptNode(nodeMap, startId);

                for (int d = 0; d < depth && !currentLevel.isEmpty(); d++) {
                    visited.addAll(currentLevel);
                    var placeholders = currentLevel.stream().map(id -> "?").collect(Collectors.joining(","));
                    var nextLevel = new HashSet<String>();

                    // 查询从当前层出发的所有关系
                    var params = new ArrayList<>(currentLevel);
                    var sql = "SELECT cr.*, cs.content AS source_name, ct.content AS target_name " +
                              "FROM concept_relations cr " +
                              "JOIN memories cs ON cr.source_id = cs.id " +
                              "JOIN memories ct ON cr.target_id = ct.id " +
                              "WHERE cr.source_id IN (" + placeholders + ")";
                    try (var pstmt = connection.prepareStatement(sql)) {
                        for (int i = 0; i < params.size(); i++) pstmt.setString(i + 1, params.get(i));
                        var rs = pstmt.executeQuery();
                        while (rs.next()) {
                            var edge = new HashMap<String, Object>();
                            edge.put("source", rs.getString("source_name"));
                            edge.put("target", rs.getString("target_name"));
                            edge.put("type", rs.getString("relation_type"));
                            edge.put("weight", rs.getDouble("weight"));
                            edgeList.add(edge);

                            var targetId = rs.getString("target_id");
                            if (!visited.contains(targetId)) {
                                nextLevel.add(targetId);
                                addConceptNode(nodeMap, targetId);
                            }
                        }
                    }
                    currentLevel = nextLevel;
                }

                return Map.of("nodes", List.copyOf(nodeMap.values()), "edges", edgeList);
            } catch (Exception e) {
                log.warn("queryGraph failed for '{}': {}", conceptName, e.getMessage());
                return Map.of("nodes", List.of(), "edges", List.of());
            }
        });
    }

    private void addConceptNode(LinkedHashMap<String, Map<String, Object>> nodeMap, String id) {
        if (nodeMap.containsKey(id)) return;
        try (var pstmt = connection.prepareStatement("SELECT * FROM memories WHERE id = ?")) {
            pstmt.setString(1, id);
            var rs = pstmt.executeQuery();
            if (rs.next()) {
                var node = new HashMap<String, Object>();
                node.put("id", id);
                node.put("name", rs.getString("content"));
                node.put("type", rs.getString("type"));
                nodeMap.put(id, node);
            }
        } catch (Exception e) {
            log.warn("Failed to fetch concept node {}: {}", id, e.getMessage());
        }
    }
}
