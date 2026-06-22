package com.owencli.contextos.memory;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Collectors;

/**
 * Character n-gram based embedding service.
 * <p>
 * Pure-Java implementation with zero external dependencies.
 * Uses Chinese character bigrams + English word trigrams to build
 * a 256-dimensional vector. Works fully offline.
 * <p>
 * While not as semantically powerful as LLM-based embeddings,
 * it captures lexical similarity effectively and runs in ~1ms.
 */
public class CharNGramEmbeddingService implements EmbeddingService {

    private static final Logger log = LoggerFactory.getLogger(CharNGramEmbeddingService.class);

    /** Vector dimension. */
    private static final int DIM = 256;

    private static final double SQRT_DIM = Math.sqrt(DIM);

    @Override
    public CompletableFuture<List<Double>> embed(String text) {
        if (text == null || text.isBlank()) {
            return CompletableFuture.completedFuture(null);
        }

        double[] vector = new double[DIM];

        // 1. Chinese character bigrams (2-char sliding window)
        String cleaned = text.replaceAll("\\s+", "");
        for (int i = 0; i < cleaned.length() - 1; i++) {
            int ch1 = cleaned.charAt(i);
            int ch2 = cleaned.charAt(i + 1);
            if (isChinese(ch1) && isChinese(ch2)) {
                int hash = (ch1 * 31 + ch2) & 0x7FFFFFFF;
                int idx = hash % DIM;
                vector[idx] += 1.0;
            }
        }

        // 2. Chinese unigrams (single chars) with position weighting
        for (int i = 0; i < cleaned.length(); i++) {
            int ch = cleaned.charAt(i);
            if (isChinese(ch)) {
                int hash = (ch * 17) & 0x7FFFFFFF;
                int idx = hash % DIM;
                vector[idx] += 0.5;
            }
        }

        // 3. English word trigrams
        String lower = text.toLowerCase();
        var words = Arrays.stream(lower.split("[^a-zA-Z0-9]+"))
                .filter(w -> w.length() >= 2)
                .collect(Collectors.toList());
        for (String word : words) {
            for (int i = 0; i < word.length() - 2; i++) {
                String tri = word.substring(i, i + 3);
                int hash = tri.hashCode() & 0x7FFFFFFF;
                int idx = hash % DIM;
                vector[idx] += 1.0;
            }
            // Whole word hash
            int hash = word.hashCode() & 0x7FFFFFFF;
            int idx = hash % DIM;
            vector[idx] += 0.8;
        }

        // 4. TF-IDF-like frequency normalization per dimension
        for (int i = 0; i < DIM; i++) {
            if (vector[i] > 0) {
                vector[i] = Math.log1p(vector[i]); // log(1 + freq)
            }
        }

        // 5. Unit-length normalization
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

    private static boolean isChinese(int codePoint) {
        return codePoint >= 0x4E00 && codePoint <= 0x9FFF;
    }
}
