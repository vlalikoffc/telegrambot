class PluginError(Exception):
    """Plugin-specific error."""


class PluginSecurityError(PluginError):
    """Security violation raised when plugin breaks sandbox rules."""

    def __init__(self, message: str, *, path: str | None = None, operation: str | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.operation = operation
