package com.owencli.contextos.core.exception;

/**
 * Raised when context building fails.
 */
public class ContextBuildException extends ContextOSException {

    public ContextBuildException(String message) {
        super(message);
    }

    public ContextBuildException(String message, Throwable cause) {
        super(message, cause);
    }
}
