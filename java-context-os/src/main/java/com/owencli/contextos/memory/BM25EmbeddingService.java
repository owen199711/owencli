package com.owencli.contextos.memory;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;

/**
 * BM25-style keyword-based embedding service.
 * <p>
 * Acts as a fallback when ONNX model is unavailable or embedding is disabled.
 * Instead of producing real vector embeddings, it generates a sparse token-frequency
 * vector that can be used for keyword matching, TF-IDF scoring, and BM25 ranking.
 * <p>
 * Suitable for:
 * <ul>
 *   <li>Resource-constrained environments (no GPU, limited memory)</li>
 *   <li>Fast startup with zero model loading</li>
 *   <li>Fallback when ONNX / API / Ollama are all unavailable</li>
 * </ul>
 */
public class BM25EmbeddingService implements EmbeddingService {

    private static final Logger log = LoggerFactory.getLogger(BM25EmbeddingService.class);

    private static final int DIM = 256;
    private static final double SQRT_DIM = Math.sqrt(DIM);
    private static final Pattern CHINESE_PATTERN = Pattern.compile("[\\u4e00-\\u9fff]");

    // Stop words to filter out
    private static final Set<String> STOP_WORDS = Set.of(
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
            "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
            "没有", "看", "好", "自己", "这", "the", "a", "an", "is", "are",
            "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "could", "should",
            "may", "might", "shall", "can", "need", "dare", "ought"
    );

    private final Map<String, Double> idfCache = new HashMap<>();
    private int docCount = 0;

    @Override
    public CompletableFuture<List<Double>> embed(String text) {
        if (text == null || text.isBlank()) {
            return CompletableFuture.completedFuture(null);
        }

        double[] vector = new double[DIM];

        // 1. Extract tokens (Chinese characters + English words)
        var tokens = extractTokens(text);

        // 2. Compute term frequency map
        var tfMap = new LinkedHashMap<String, Integer>();
        for (var token : tokens) {
            if (token.length() < 2 || STOP_WORDS.contains(token)) continue;
            tfMap.merge(token, 1, Integer::sum);
        }

        if (tfMap.isEmpty()) {
            return CompletableFuture.completedFuture(new ArrayList<>());
        }

        // 3. Hash tokens into vector dimensions with TF weighting
        double maxTf = tfMap.values().stream().mapToInt(Integer::intValue).max().orElse(1);
        for (var entry : tfMap.entrySet()) {
            String token = entry.getKey();
            int tf = entry.getValue();

            // TF normalization (BM25-style)
            double tfNorm = (double) tf / (0.5 + 0.5 * (double) tf / maxTf);

            // Hash token to dimension
            int hash = token.hashCode() & 0x7FFFFFFF;
            int idx = hash % DIM;
            int idx2 = (hash * 31 + 17) % DIM; // secondary hash for robustness

            double idf = getIdf(token);
            vector[idx] += tfNorm * idf;
            vector[idx2] += tfNorm * idf * 0.3; // spread to secondary dimension
        }

        // 4. L2-normalize
        double norm = 0.0;
        for (int i = 0; i < DIM; i++) {
            norm += vector[i] * vector[i];
        }
        norm = Math.sqrt(norm);
        if (norm > 0) {
            for (int i = 0; i < DIM; i++) {
                vector[i] /= norm;
            }
        }

        var result = new ArrayList<Double>(DIM);
        for (double v : vector) result.add(v);
        return CompletableFuture.completedFuture(result);
    }

    /**
     * Extract meaningful tokens from text (Chinese chars + English words).
     */
    private List<String> extractTokens(String text) {
        var tokens = new ArrayList<String>();
        String lower = text.toLowerCase();

        // Chinese characters (each char as a token)
        var chineseMatcher = CHINESE_PATTERN.matcher(lower);
        var chineseBuilder = new StringBuilder();
        while (chineseMatcher.find()) {
            chineseBuilder.append(chineseMatcher.group());
        }
        // Chinese bigrams
        String chineseSeq = chineseBuilder.toString();
        for (int i = 0; i < chineseSeq.length() - 1; i++) {
            tokens.add(chineseSeq.substring(i, i + 2));
        }

        // English words
        for (var word : lower.split("[^a-z0-9]+")) {
            if (word.length() >= 2) {
                tokens.add(word);
            }
        }

        return tokens;
    }

    /**
     * Get IDF weight for a token. Uses a simple simulated IDF
     * (can be replaced with actual corpus statistics).
     */
    private double getIdf(String token) {
        return idfCache.computeIfAbsent(token, k -> {
            // Simulated IDF: less common tokens get higher weight
            // In production, compute from actual corpus
            int hash = k.hashCode() & 0x7FFFFFFF;
            double simulatedDf = 1.0 + (hash % 100) / 100.0;
            return Math.log(1.0 + (1000.0 - simulatedDf) / simulatedDf);
        });
    }

    /**
     * BM25 score between a query and a document.
     */
    public double bm25Score(String query, String document) {
        if (query == null || document == null) return 0.0;

        var queryTokens = extractTokens(query);
        var docTokens = extractTokens(document);

        if (queryTokens.isEmpty() || docTokens.isEmpty()) return 0.0;

        var docTf = new LinkedHashMap<String, Integer>();
        for (var token : docTokens) {
            if (token.length() >= 2) docTf.merge(token, 1, Integer::sum);
        }

        double avgDocLen = docTokens.size();
        double k1 = 1.2;
        double b = 0.75;
        double score = 0.0;

        for (var qt : new LinkedHashSet<>(queryTokens)) {
            if (qt.length() < 2 || STOP_WORDS.contains(qt)) continue;
            int tf = docTf.getOrDefault(qt, 0);
            if (tf == 0) continue;

            double idf = getIdf(qt);
            score += idf * ((double) tf * (k1 + 1)) / (tf + k1 * (1 - b + b * docTokens.size() / avgDocLen));
        }

        return score;
    }
}
