class ConfigError(RuntimeError):
    """Raised when the YAML configuration is invalid."""


class ProcessingError(RuntimeError):
    """Raised when a download or media-processing step fails."""


class SeparationError(RuntimeError):
    """Raised when the audio separation backend cannot run."""
