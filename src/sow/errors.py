"""Errors raised by configuration, discovery, and execution."""


class SowError(Exception):
    """Base error for sow configuration, discovery, and execution."""


class SowConfigError(SowError):
    """Raised when configuration is missing or invalid."""


class SowModuleError(SowError):
    """Raised when a seed or task module cannot be imported or executed."""
