"""Typed resource-limit failures for controlled acquisition (ADR 0009)."""

from __future__ import annotations


class ResourceLimitExceeded(RuntimeError):
    """Base for configured safeguard breaches that must map to fatal QualityIssues."""

    code: str = "RESOURCE_LIMIT_EXCEEDED"


class MaxFileBytesExceeded(ResourceLimitExceeded):
    code = "MAX_FILE_BYTES_EXCEEDED"


class MaxExternalDependencyBytesExceeded(ResourceLimitExceeded):
    code = "MAX_EXTERNAL_DEPENDENCY_BYTES_EXCEEDED"


class MaxRedirectsExceeded(ResourceLimitExceeded):
    code = "MAX_REDIRECTS_EXCEEDED"


class MaxBundleBytesExceeded(ResourceLimitExceeded):
    code = "MAX_BUNDLE_BYTES_EXCEEDED"


class LogicalPathConflict(RuntimeError):
    """Raised when a logical payload path is reused with different content identity."""
