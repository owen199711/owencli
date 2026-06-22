package com.owencli.contextos.runtime;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Retry Policy — determines retry behavior for failed operations.
 * Implements exponential backoff and max retry limits.
 */
public class RetryPolicy {

    private static final Logger log = LoggerFactory.getLogger(RetryPolicy.class);

    private final int maxRetries;
    private final long baseDelayMs;
    private final Map<String, Integer> retryCounts = new ConcurrentHashMap<>();

    public RetryPolicy() {
        this(3, 1000);
    }

    public RetryPolicy(int maxRetries, long baseDelayMs) {
        this.maxRetries = maxRetries;
        this.baseDelayMs = baseDelayMs;
        log.info("RetryPolicy: maxRetries={}, baseDelay={}ms", maxRetries, baseDelayMs);
    }

    public boolean shouldRetry(String operationId) {
        int current = retryCounts.getOrDefault(operationId, 0);
        return current < maxRetries;
    }

    public long getDelayMs(String operationId) {
        int current = retryCounts.getOrDefault(operationId, 0);
        return baseDelayMs * (long) Math.pow(2, current);
    }

    public void recordAttempt(String operationId) {
        int current = retryCounts.getOrDefault(operationId, 0);
        current++;
        retryCounts.put(operationId, current);
        if (current > maxRetries) {
            log.warn("Max retries ({}) reached for operation: {}", maxRetries, operationId);
        }
    }

    public void recordSuccess(String operationId) {
        retryCounts.remove(operationId);
        log.debug("Retry count reset for successful operation: {}", operationId);
    }

    public int getCurrentRetryCount(String operationId) {
        return retryCounts.getOrDefault(operationId, 0);
    }

    public int getMaxRetries() { return maxRetries; }
}
