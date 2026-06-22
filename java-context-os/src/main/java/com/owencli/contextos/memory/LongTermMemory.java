package com.owencli.contextos.memory;

import com.owencli.contextos.core.model.MemoryItem;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Long-Term Memory — cross-session persistent knowledge base.
 * <p>
 * Supports both keyword-based and vector similarity retrieval.
 */
public class LongTermMemory {

    private static final Logger log = LoggerFactory.getLogger(LongTermMemory.class);

    private final SQLiteStore store;
    private final String userId;
    private final EmbeddingService embeddingService;

    // 用于提取中文关键词的正则
    private static final Pattern CHINESE_PATTERN = Pattern.compile("[\\u4e00-\\u9fff]{2,}");
    // 过滤掉的无意义中文词
    private static final Set<String> STOP_WORDS = Set.of(
            "什么", "怎么", "如何", "这个", "那个", "一个", "可以", "没有",
            "就是", "不是", "但是", "而且", "因为", "所以", "如果", "虽然",
            "我们", "你们", "他们", "自己", "知道", "这样", "那样",
            "刚才", "之前", "之后", "现在", "请问", "需要", "想要", "能够"
    );

    public LongTermMemory(SQLiteStore store, String userId, EmbeddingService embeddingService) {
        this.store = store;
        this.userId = userId;
        this.embeddingService = embeddingService;
        log.info("LongTermMemory initialized (user={}, embedding={})", userId,
                embeddingService.getClass().getSimpleName());
    }

    public CompletableFuture<String> save(String content) {
        return save(content, "long_term", null, null, null);
    }

    /**
     * Save a memory with automatic embedding generation.
     */
    public CompletableFuture<String> save(String content, String memoryType,
                                          Map<String, Object> metadata,
                                          List<Double> embedding, String userId) {
        String memId = UUID.randomUUID().toString().replace("-", "");
        String effectiveUserId = userId != null ? userId : this.userId;

        // 生成 embedding（如果未提供）
        CompletableFuture<List<Double>> embFuture;
        if (embedding != null) {
            embFuture = CompletableFuture.completedFuture(embedding);
        } else {
            embFuture = embeddingService.embed(content);
        }

        return embFuture.thenCompose(emb -> store.saveMemory(memId,
                        memoryType != null ? memoryType : "long_term",
                        content, null, effectiveUserId,
                        emb, metadata, null))
                .thenApply(id -> {
                    log.info("LTM saved: id={}, type={}, content_len={}, has_embedding={}",
                            memId, memoryType, content.length(), embedding != null || true);
                    return id;
                });
    }

    /**
     * Retrieve memories using combined keyword + vector search.
     */
    public CompletableFuture<List<MemoryItem>> retrieve(String query, int topK,
                                                        String memoryType, List<Double> embedding) {
        var keywords = extractKeywords(query);

        // 如果有 query 但没提供 embedding，自动生成
        CompletableFuture<List<Double>> embFuture;
        if (embedding != null) {
            embFuture = CompletableFuture.completedFuture(embedding);
        } else if (query != null && !query.isBlank()) {
            embFuture = embeddingService.embed(query);
        } else {
            embFuture = CompletableFuture.completedFuture(null);
        }

        return embFuture.thenCompose(queryEmb -> store.queryMemories(
                        memoryType != null ? memoryType : "long_term",
                        null, this.userId, query, keywords, queryEmb, topK, 0))
                .thenApply(results -> results.stream().map(r -> {
                    var item = new MemoryItem();
                    item.setId((String) r.get("id"));
                    item.setContent((String) r.get("content"));

                    // 使用向量得分优先，fallback 到关键词得分
                    double vecScore = (double) r.getOrDefault("_vector_score",
                            r.getOrDefault("_cosine_sim", 0.0));
                    if (vecScore > 0.0) {
                        item.setRelevanceScore(Math.min(1.0, vecScore));
                    } else {
                        item.setRelevanceScore(computeKeywordRelevance(query, keywords, r));
                    }
                    return item;
                }).collect(Collectors.toList()));
    }

    /**
     * 从查询文本中提取有意义的关键词。
     */
    private List<String> extractKeywords(String query) {
        if (query == null || query.isBlank()) return List.of();

        var keywords = new LinkedHashSet<String>(); // 去重且保持顺序

        // 1. 提取中文词组（连续 2+ 个汉字）
        var chineseMatcher = CHINESE_PATTERN.matcher(query);
        while (chineseMatcher.find()) {
            String word = chineseMatcher.group();
            if (!STOP_WORDS.contains(word)) {
                keywords.add(word);
            }
        }

        // 2. 提取英文单词（长度 >= 3）
        for (var word : query.toLowerCase().split("[^a-zA-Z0-9]+")) {
            if (word.length() >= 3) {
                keywords.add(word);
            }
        }

        var result = new ArrayList<>(keywords);
        log.debug("Extracted {} keywords from query: {}", result.size(), result);
        return result;
    }

    /**
     * 仅基于关键词的记忆相关性得分（在没有向量得分时的 fallback）。
     */
    private double computeKeywordRelevance(String query, List<String> keywords, Map<String, Object> row) {
        double score = 0.0;
        String content = (String) row.getOrDefault("content", "");

        if (content.isBlank()) return 0.0;

        // 1. 原始 query 匹配加分
        if (query != null && !query.isEmpty() && content.contains(query)) {
            score += 0.5;
        }

        // 2. 关键词匹配计数
        if (keywords != null && !keywords.isEmpty()) {
            long matchCount = keywords.stream().filter(kw -> content.contains(kw)).count();
            score += (double) matchCount / keywords.size() * 0.5;
        }

        // 3. 限制在 [0, 1] 范围
        return Math.min(1.0, score);
    }

    public CompletableFuture<Integer> consolidate() {
        return store.queryMemories("long_term", null, this.userId, null, null, 1000, 0)
                .thenCompose(results -> {
                    Set<String> seenContents = new HashSet<>();
                    List<String> toDelete = new ArrayList<>();
                    for (var r : results) {
                        String content = ((String) r.getOrDefault("content", "")).trim();
                        if (seenContents.contains(content)) {
                            toDelete.add((String) r.get("id"));
                        } else {
                            seenContents.add(content);
                        }
                    }
                    List<CompletableFuture<Void>> deletes = toDelete.stream()
                            .map(store::deleteMemory)
                            .collect(Collectors.toList());
                    return CompletableFuture.allOf(deletes.toArray(new CompletableFuture[0]))
                            .thenApply(v -> toDelete.size());
                })
                .thenApply(count -> {
                    if (count > 0) log.info("LTM consolidated: removed {} duplicates", count);
                    return count;
                });
    }
}
