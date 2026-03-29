"""Data models for manifest validation results.

All models use frozen dataclasses to ensure immutability. Mutation methods
return new instances rather than modifying existing ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from opentree.manifest.errors import ErrorCode


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation issue found during manifest validation.

    Attributes:
        code: The error code identifying the type of issue.
        message: A human-readable description of the issue.
        path: JSON path to the problematic field (e.g. "loading.rules[0]").
        severity: Whether this issue is an error or a warning.
    """

    code: ErrorCode
    message: str
    path: str = ""
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True)
class ManifestValidation:
    """The result of validating a module manifest.

    Attributes:
        is_valid: True if no error-level issues were found.
        issues: Tuple of all validation issues (errors and warnings).
        manifest_path: The file path of the validated manifest.
    """

    is_valid: bool
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    manifest_path: str = ""

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        """Return only error-level issues."""
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        """Return only warning-level issues."""
        return tuple(i for i in self.issues if i.severity == "warning")
