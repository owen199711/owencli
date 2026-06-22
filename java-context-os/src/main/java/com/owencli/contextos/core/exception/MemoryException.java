package com.owencli.contextos.core.exception;

/**
 * Raised when memory operations fail.
 */
public class MemoryException extends ContextOSException {

    public MemoryException(String message) {
        super(message);
    }

    public MemoryException(String message, Throwable cause) {
        super(message, cause);
    }
}
