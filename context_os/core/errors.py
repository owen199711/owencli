class ContextOSError(Exception):
    """Base exception for Context-OS system."""
    pass


class ContextBuildError(ContextOSError):
    """Raised when context building fails."""
    pass


class MemoryError(ContextOSError):
    """Raised when memory operations fail."""
    pass
