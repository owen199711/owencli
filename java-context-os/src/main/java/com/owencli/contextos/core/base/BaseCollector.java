package com.owencli.contextos.core.base;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Base class for context collectors.
 * Each collector is responsible for fetching data from a specific source.
 */
public interface BaseCollector {

    /**
     * Collect data from the source and return as a Map.
     */
    CompletableFuture<Map<String, Object>> collect();
}
