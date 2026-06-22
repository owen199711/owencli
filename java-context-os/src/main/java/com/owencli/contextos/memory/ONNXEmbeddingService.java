package com.owencli.contextos.memory;

import ai.onnxruntime.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;

/**
 * ONNX-based embedding service — loads a local .onnx model (e.g. bge-small, gte-small)
 * and runs inference entirely in Java via ONNX Runtime.
 * <p>
 * No Python, no CUDA, no external services required. The model file should be
 * placed in the configured path (default: {@code ./models/bge-small.onnx}).
 * A ~100-150MB ONNX model provides quality embeddings fully offline.
 */
public class ONNXEmbeddingService implements EmbeddingService {

    private static final Logger log = LoggerFactory.getLogger(ONNXEmbeddingService.class);

    private static final int DEFAULT_DIM = 384; // bge-small/gte-small default dimension
    private static final String INPUT_NAME = "input_ids";
    private static final String ATTENTION_MASK = "attention_mask";
    private static final String TOKEN_TYPE_IDS = "token_type_ids";
    private static final String OUTPUT_NAME = "last_hidden_state";

    private OrtSession session;
    private OrtEnvironment env;
    private int dimension;
    private final String modelPath;
    private boolean available = false;

    /**
     * Create ONNX embedding service by loading model from file path.
     * Gracefully handles native library loading failures (e.g. missing VC++ runtime).
     *
     * @param modelPath Absolute or relative path to the .onnx model file.
     */
    public ONNXEmbeddingService(String modelPath) {
        this.modelPath = modelPath;
        try {
            this.env = OrtEnvironment.getEnvironment();
        } catch (Throwable t) {
            log.warn("ONNX Runtime native library not available ({}), service disabled", t.getMessage());
            this.env = null;
            this.session = null;
            this.dimension = 0;
            this.available = false;
            return;
        }

        try {
            // Try loading from absolute/relative file path
            File modelFile = new File(modelPath);
            if (modelFile.exists()) {
                this.session = env.createSession(modelPath, new OrtSession.SessionOptions());
                this.dimension = detectDimension();
                this.available = true;
                log.info("ONNX model loaded: path={}, dimension={}", modelFile.getAbsolutePath(), dimension);
            } else {
                // Try loading from classpath resources (bundled models)
                try (InputStream is = getClass().getClassLoader().getResourceAsStream(modelPath)) {
                    if (is != null) {
                        Path tempFile = Files.createTempFile("onnx_model_", ".onnx");
                        tempFile.toFile().deleteOnExit();
                        Files.copy(is, tempFile, StandardCopyOption.REPLACE_EXISTING);
                        this.session = env.createSession(tempFile.toAbsolutePath().toString(), new OrtSession.SessionOptions());
                        this.dimension = detectDimension();
                        this.available = true;
                        log.info("ONNX model loaded from classpath: resource={}, dimension={}", modelPath, dimension);
                    } else {
                        log.warn("ONNX model file not found at: {}", modelPath);
                        this.session = null;
                        this.dimension = 0;
                        this.available = false;
                    }
                } catch (Exception e) {
                    log.warn("Failed to load ONNX model from classpath: {}", e.getMessage());
                    this.session = null;
                    this.dimension = 0;
                    this.available = false;
                }
            }
        } catch (Throwable t) {
            log.warn("ONNX model loading failed ({}), service disabled", t.getMessage());
            this.session = null;
            this.dimension = 0;
            this.available = false;
        }
    }

    private int detectDimension() throws OrtException {
        try {
            var outputInfo = session.getOutputInfo();
            var info = outputInfo.get(OUTPUT_NAME);
            if (info != null && info.getInfo() instanceof TensorInfo tensorInfo) {
                var shape = tensorInfo.getShape();
                if (shape.length >= 2 && shape[shape.length - 1] > 0) {
                    return (int) shape[shape.length - 1];
                }
            }
        } catch (Exception e) {
            log.debug("Could not detect output dimension from model, using default {}", DEFAULT_DIM);
        }
        return DEFAULT_DIM;
    }

    @Override
    public CompletableFuture<List<Double>> embed(String text) {
        if (text == null || text.isBlank()) {
            return CompletableFuture.completedFuture(null);
        }
        if (!available) {
            return CompletableFuture.completedFuture(new ArrayList<>());
        }

        try {
            // Tokenize: simple whitespace + punctuation split for ONNX models
            // Real production should use a proper tokenizer (e.g. from HuggingFace tokenizers-java)
            var tokens = simpleTokenize(text, 128);
            long[] inputIds = tokens[0];
            long[] attentionMask = tokens[1];

            // Create input tensors
            var inputIdsTensor = OnnxTensor.createTensor(env, new long[][]{inputIds});
            var attentionMaskTensor = OnnxTensor.createTensor(env, new long[][]{attentionMask});

            // Run inference
            try (var outputs = session.run(java.util.Map.of(
                    INPUT_NAME, inputIdsTensor,
                    ATTENTION_MASK, attentionMaskTensor
            ))) {
                // Extract embedding from output
                var outputTensor = (OnnxTensor) outputs.get(OUTPUT_NAME)
                        .orElseThrow(() -> new OrtException("Output not found: " + OUTPUT_NAME));
                float[][] embeddingData = (float[][]) outputTensor.getValue();
                float[] pooled = meanPool(embeddingData, attentionMask);

                // L2 normalize
                double norm = 0.0;
                for (float v : pooled) norm += v * v;
                norm = Math.sqrt(norm);

                var resultList = new ArrayList<Double>(pooled.length);
                for (float v : pooled) {
                    resultList.add(norm > 0 ? (double) v / norm : 0.0);
                }
                return CompletableFuture.completedFuture(resultList);
            }
        } catch (Exception e) {
            log.warn("ONNX embedding failed: {}", e.getMessage());
            return CompletableFuture.completedFuture(new ArrayList<>());
        }
    }

    /**
     * Mean pooling over non-padded tokens.
     */
    private float[] meanPool(float[][] tokenEmbeddings, long[] attentionMask) {
        int seqLen = tokenEmbeddings.length;
        int dim = tokenEmbeddings[0].length;
        float[] pooled = new float[dim];
        float tokenCount = 0;

        for (int i = 0; i < seqLen; i++) {
            if (i < attentionMask.length && attentionMask[i] == 0) continue;
            tokenCount++;
            for (int j = 0; j < dim; j++) {
                pooled[j] += tokenEmbeddings[i][j];
            }
        }

        if (tokenCount > 0) {
            for (int j = 0; j < dim; j++) {
                pooled[j] /= tokenCount;
            }
        }
        return pooled;
    }

    /**
     * Simple whitespace/punctuation tokenization.
     * For production, replace with HuggingFace tokenizers-java.
     */
    private long[][] simpleTokenize(String text, int maxLen) {
        // Very basic tokenization: split on whitespace and punctuation
        String clean = text.toLowerCase().trim();
        String[] words = clean.split("[^a-zA-Z0-9\\u4e00-\\u9fff]+");

        // [CLS] token=101, [SEP] token=102, [PAD] token=0
        int seqLen = Math.min(words.length + 2, maxLen); // +2 for [CLS] and [SEP]
        long[] inputIds = new long[seqLen];
        long[] attentionMask = new long[seqLen];

        inputIds[0] = 101; // [CLS]
        attentionMask[0] = 1;

        for (int i = 0; i < Math.min(words.length, maxLen - 2); i++) {
            if (!words[i].isEmpty()) {
                // Simple hash-based token ID generation for unknown vocab
                inputIds[i + 1] = (words[i].hashCode() & 0x7FFFFFFF) % 30522 + 1;
                attentionMask[i + 1] = 1;
            }
        }

        int lastPos = Math.min(words.length, maxLen - 2) + 1;
        if (lastPos < seqLen) {
            inputIds[lastPos] = 102; // [SEP]
            attentionMask[lastPos] = 1;
        }

        return new long[][]{inputIds, attentionMask};
    }

    public int getDimension() { return dimension; }
    public String getModelPath() { return modelPath; }
    public boolean isAvailable() { return available; }
}
