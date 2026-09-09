"""Shared exception types for later phases."""


class VoicePilotError(Exception):
    """Base application error."""


class ConfigurationError(VoicePilotError):
    """Invalid application configuration."""


class SecurityError(VoicePilotError):
    """An operation violates security policy."""


class ToolExecutionError(VoicePilotError):
    """A tool failed to execute."""


class VerificationError(VoicePilotError):
    """An outcome could not be verified."""
