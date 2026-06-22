package com.owencli.contextos.memory;

import java.util.List;
import java.util.concurrent.CompletableFuture;

/**
 * Embedding service — converts text to vector representation.
 * <p>
 * Implementations can use LLM APIs (e.g. DeepSeek embedding endpoint)
 * or local algorithms (character n-gram, etc.).
 */
public interface EmbeddingService {

    /**
     * Generate an embedding vector for the given text.
     *
     * @param text Input text.
     * @return Embedding vector (List of doubles), or null/empty if embedding fails.
     */
    CompletableFuture<List<Double>> embed(String text);

    /**
     * Compute cosine similarity between two embedding vectors.
     */
    static double cosineSimilarity(List<Double> a, List<Double> b) {
        if (a == null || b == null || a.isEmpty() || b.isEmpty() || a.size() != b.size()) {
            return 0.0;
        }
        double dot = 0.0, normA = 0.0, normB = 0.0;
        for (int i = 0; i < a.size(); i++) {
            double va = a.get(i);
            double vb = b.get(i);
            dot += va * vb;
            normA += va * va;
            normB += vb * vb;
        }
        double denom = Math.sqrt(normA) * Math.sqrt(normB);
        return denom == 0.0 ? 0.0 : dot / denom;
    }
}
