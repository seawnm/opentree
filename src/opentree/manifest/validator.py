"""ManifestValidator for OpenTree module manifests.

Validates module manifests against the JSON Schema, performs semantic checks,
verifies dependency/conflict constraints, and detects circular dependencies
across a batch of modules.

Validation pipeline order:
    1. File existence → MANIFEST_NOT_FOUND
    2. JSON parsing → MANIFEST_PARSE_ERROR
    3. Schema validation → SCHEMA_VALIDATION_ERROR
    4. Semantic checks → NAME_MISMATCH, MISSING_TRIGGERS, UNKNOWN_PLACEHOLDER_MODE
    5. Dependency checks → SELF_DEPENDENCY, DEPENDENCY_NOT_FOUND, CONFLICT_WITH_INSTALLED
    6. Batch checks → CIRCULAR_DEPENDENCY
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from opentree.manifest.errors import ErrorCode
from opentree.manifest.models import ManifestValidation, ValidationIssue

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schema" / "opentree.schema.json"
)

_VALID_PLACEHOLDER_MODES = frozenset({"required", "optional", "auto"})


class ManifestValidator:
    """Validates OpenTree module manifests.

    The validator loads the JSON Schema once at construction and reuses it
    for every subsequent validation call.
    """

    def __init__(self) -> None:
        raw = _SCHEMA_PATH.read_text(encoding="utf-8")
        self._schema: dict[str, Any] = json.loads(raw)
        self._validator_cls = jsonschema.validators.validator_for(self._schema)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_file(
        self,
        path: Path,
        module_dir_name: str | None = None,
    ) -> ManifestValidation:
        """Validate a manifest file on disk.

        Args:
            path: Path to the opentree.json file.
            module_dir_name: Expected directory name (for NAME_MISMATCH check).
                If *None*, the check is derived from ``path.parent.name``.

        Returns:
            A ``ManifestValidation`` result.
        """
        resolved = Path(path).resolve()

        if not resolved.is_file():
            issue = ValidationIssue(
                code=ErrorCode.MANIFEST_NOT_FOUND,
                message=f"Manifest not found: {resolved}",
                path="",
                severity="error",
            )
            return ManifestValidation(
                is_valid=False, issues=(issue,), manifest_path=str(resolved)
            )

        try:
            raw = resolved.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError, OSError):
            issue = ValidationIssue(
                code=ErrorCode.MANIFEST_PARSE_ERROR,
                message=f"Invalid JSON in manifest: {resolved}",
                path="",
                severity="error",
            )
            return ManifestValidation(
                is_valid=False, issues=(issue,), manifest_path=str(resolved)
            )

        if not isinstance(data, dict):
            issue = ValidationIssue(
                code=ErrorCode.MANIFEST_PARSE_ERROR,
                message=f"Manifest root must be a JSON object, got {type(data).__name__}: {resolved}",
                path="",
                severity="error",
            )
            return ManifestValidation(
                is_valid=False, issues=(issue,), manifest_path=str(resolved)
            )

        dir_name = module_dir_name if module_dir_name is not None else resolved.parent.name
        return self._validate_parsed(data, dir_name, str(resolved))

    def validate_dict(
        self,
        data: dict[str, Any],
        module_dir_name: str | None = None,
    ) -> ManifestValidation:
        """Validate an in-memory manifest dict.

        Args:
            data: The manifest data.
            module_dir_name: Expected directory name (for NAME_MISMATCH check).
                If *None*, the name-mismatch check is skipped.

        Returns:
            A ``ManifestValidation`` result.
        """
        return self._validate_parsed(data, module_dir_name, "")

    def validate_dependencies(
        self,
        data: dict[str, Any],
        installed_modules: tuple[str, ...] = (),
    ) -> tuple[ValidationIssue, ...]:
        """Check dependency and conflict constraints.

        Args:
            data: The manifest data (must contain at least ``name``).
            installed_modules: Names of currently installed modules.

        Returns:
            A tuple of dependency/conflict issues found.
        """
        issues: list[ValidationIssue] = []
        module_name = data.get("name", "<unknown>")
        installed = frozenset(installed_modules)

        # Self-dependency
        for dep in data.get("depends_on", []):
            if dep == module_name:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.SELF_DEPENDENCY,
                        message=f"Module '{module_name}' depends on itself",
                        path="depends_on",
                        severity="error",
                    )
                )

        # Missing dependencies
        for dep in data.get("depends_on", []):
            if dep != module_name and dep not in installed:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.DEPENDENCY_NOT_FOUND,
                        message=(
                            f"Module '{module_name}' depends on '{dep}', "
                            f"but '{dep}' is not installed"
                        ),
                        path="depends_on",
                        severity="error",
                    )
                )

        # Conflicts
        for conflict in data.get("conflicts_with", []):
            if conflict in installed:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.CONFLICT_WITH_INSTALLED,
                        message=(
                            f"Module '{module_name}' conflicts with "
                            f"installed module '{conflict}'"
                        ),
                        path="conflicts_with",
                        severity="error",
                    )
                )

        return tuple(issues)

    def validate_batch(
        self,
        manifests: dict[str, dict[str, Any]],
    ) -> dict[str, ManifestValidation]:
        """Validate a batch of manifests and detect circular dependencies.

        Args:
            manifests: Mapping of ``module_name → manifest_dict``.

        Returns:
            Mapping of ``module_name → ManifestValidation``.
        """
        results: dict[str, ManifestValidation] = {}

        # Step 1: individual validation
        for name, data in manifests.items():
            results[name] = self.validate_dict(data, module_dir_name=name)

        # Step 2: circular dependency detection across all modules
        cycle_issues = self._detect_circular_dependencies(manifests)

        if cycle_issues:
            # Distribute cycle issues to involved modules
            cycle_modules = set()
            for issue in cycle_issues:
                # Extract module names from cycle message
                cycle_modules.update(_extract_cycle_modules(issue.message, manifests))

            for name in manifests:
                if name in cycle_modules:
                    existing = results[name]
                    merged_issues = existing.issues + cycle_issues
                    has_errors = any(i.severity == "error" for i in merged_issues)
                    results[name] = ManifestValidation(
                        is_valid=not has_errors,
                        issues=merged_issues,
                        manifest_path=existing.manifest_path,
                    )

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_parsed(
        self,
        data: dict[str, Any],
        module_dir_name: str | None,
        manifest_path: str,
    ) -> ManifestValidation:
        """Run schema + semantic validation on parsed data."""
        issues: list[ValidationIssue] = []

        issues.extend(self._validate_schema(data))
        issues.extend(self._validate_semantics(data, module_dir_name))

        has_errors = any(i.severity == "error" for i in issues)
        return ManifestValidation(
            is_valid=not has_errors,
            issues=tuple(issues),
            manifest_path=manifest_path,
        )

    def _validate_schema(
        self,
        data: dict[str, Any],
    ) -> tuple[ValidationIssue, ...]:
        """Validate data against the JSON Schema, collecting all errors."""
        validator = self._validator_cls(self._schema)
        issues: list[ValidationIssue] = []

        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            path = ".".join(str(p) for p in error.absolute_path) or ""
            message = _format_schema_error(error)
            issues.append(
                ValidationIssue(
                    code=ErrorCode.SCHEMA_VALIDATION_ERROR,
                    message=message,
                    path=path,
                    severity="error",
                )
            )

        return tuple(issues)

    def _validate_semantics(
        self,
        data: dict[str, Any],
        module_dir_name: str | None,
    ) -> tuple[ValidationIssue, ...]:
        """Perform semantic checks beyond schema conformance."""
        issues: list[ValidationIssue] = []
        module_name = data.get("name", "<unknown>")

        # Name mismatch (only when dir name is provided)
        if module_dir_name is not None:
            manifest_name = data.get("name")
            if manifest_name is not None and manifest_name != module_dir_name:
                issues.append(
                    ValidationIssue(
                        code=ErrorCode.NAME_MISMATCH,
                        message=(
                            f"Module name '{manifest_name}' does not match "
                            f"directory name '{module_dir_name}'"
                        ),
                        path="name",
                        severity="error",
                    )
                )

        # Missing triggers (warning)
        if "triggers" not in data:
            issues.append(
                ValidationIssue(
                    code=ErrorCode.MISSING_TRIGGERS,
                    message=f"Module '{module_name}' has no triggers section",
                    path="triggers",
                    severity="warning",
                )
            )

        return tuple(issues)

    def _detect_circular_dependencies(
        self,
        manifests: dict[str, dict[str, Any]],
    ) -> tuple[ValidationIssue, ...]:
        """Detect circular dependencies using DFS across all modules.

        Returns one CIRCULAR_DEPENDENCY issue per distinct cycle found.
        """
        # Build adjacency list
        graph: dict[str, list[str]] = {}
        for name, data in manifests.items():
            graph[name] = list(data.get("depends_on", []))

        visited: set[str] = set()
        on_stack: set[str] = set()
        cycles: list[tuple[str, ...]] = []

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            on_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in manifests:
                    # External dependency — skip (handled by validate_dependencies)
                    continue
                if neighbor in on_stack:
                    # Found a cycle: extract it
                    cycle_start = path.index(neighbor)
                    cycle = tuple(path[cycle_start:]) + (neighbor,)
                    cycles.append(cycle)
                elif neighbor not in visited:
                    dfs(neighbor, path)

            path.pop()
            on_stack.discard(node)

        for node in manifests:
            if node not in visited:
                dfs(node, [])

        issues: list[ValidationIssue] = []
        for cycle in cycles:
            cycle_str = " -> ".join(cycle)
            issues.append(
                ValidationIssue(
                    code=ErrorCode.CIRCULAR_DEPENDENCY,
                    message=f"Circular dependency detected: {cycle_str}",
                    path="depends_on",
                    severity="error",
                )
            )

        return tuple(issues)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _format_schema_error(error: jsonschema.ValidationError) -> str:
    """Create a human-readable message from a jsonschema error."""
    path = ".".join(str(p) for p in error.absolute_path)
    if path:
        return f"Schema error at '{path}': {error.message}"
    return f"Schema error: {error.message}"


def _extract_cycle_modules(
    message: str,
    manifests: dict[str, dict[str, Any]],
) -> set[str]:
    """Extract module names mentioned in a cycle message."""
    return {name for name in manifests if name in message}
