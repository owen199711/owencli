package com.owencli.contextos.core.exception;

/**
 * Base exception for Context-OS system.
 */
public class ContextOSException extends RuntimeException {

    public ContextOSException(String message) {
        super(message);
    }

    public ContextOSException(String message, Throwable cause) {
        super(message, cause);
    }
}
