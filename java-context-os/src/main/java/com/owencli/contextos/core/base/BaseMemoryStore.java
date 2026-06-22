package com.owencli.contextos.core.base;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Base class for memory storage backends.
 */
public interface BaseMemoryStore {

    /**
     * Retrieve memory items relevant to the query.
     */
    CompletableFuture<List<Map<String, Object>>> retrieve(String query, int topK);

    /**
     * Store a memory item.
     */
    CompletableFuture<Void> store(Map<String, Object> item);

    /**
     * Delete a memory item by ID.
     */
    CompletableFuture<Void> delete(String itemId);
}
