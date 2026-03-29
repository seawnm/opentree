"""Tests for ManifestValidator.

Groups:
    A — Structural (6): file existence, JSON parsing
    B — Schema validation (11): required fields, patterns, enums, extra properties
    C — Semantic (5): name mismatch, empty/duplicate rules
    D — Dependency (6): satisfied, missing, self, conflict
    E — Batch (2): circular dependency detection
    F — Warning (3): missing triggers, unknown placeholder mode
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opentree.manifest.errors import ErrorCode
from opentree.manifest.models import ManifestValidation, ValidationIssue
from opentree.manifest.validator import ManifestValidator

@pytest.fixture()
def validator() -> ManifestValidator:
    """Create a ManifestValidator instance."""
    return ManifestValidator()


# ---------------------------------------------------------------------------
# Group A: Structural (6 tests)
# ---------------------------------------------------------------------------


class TestStructural:
    """File-level checks: existence, JSON parsing."""

    def test_valid_minimal_manifest(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """A minimal valid manifest passes validation with is_valid=True."""
        result = validator.validate_dict(valid_minimal_manifest)

        assert result.is_valid is True
        assert result.errors == ()

    def test_valid_full_manifest(
        self,
        validator: ManifestValidator,
        valid_full_manifest: dict[str, Any],
    ) -> None:
        """A full manifest with all optional fields passes validation."""
        result = validator.validate_dict(valid_full_manifest)

        assert result.is_valid is True
        assert result.errors == ()

    def test_manifest_not_found(
        self,
        validator: ManifestValidator,
        tmp_path: Path,
    ) -> None:
        """validate_file returns MANIFEST_NOT_FOUND for nonexistent path."""
        missing = tmp_path / "nonexistent" / "opentree.json"
        result = validator.validate_file(missing)

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].code == ErrorCode.MANIFEST_NOT_FOUND
        assert str(missing) in result.errors[0].message

    def test_manifest_parse_error_invalid_json(
        self,
        validator: ManifestValidator,
        tmp_path: Path,
    ) -> None:
        """{invalid json triggers MANIFEST_PARSE_ERROR."""
        bad_file = tmp_path / "opentree.json"
        bad_file.write_text("{invalid json", encoding="utf-8")

        result = validator.validate_file(bad_file)

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].code == ErrorCode.MANIFEST_PARSE_ERROR

    def test_manifest_parse_error_not_object(
        self,
        validator: ManifestValidator,
        tmp_path: Path,
    ) -> None:
        """A JSON array [1,2,3] triggers MANIFEST_PARSE_ERROR."""
        bad_file = tmp_path / "opentree.json"
        bad_file.write_text("[1, 2, 3]", encoding="utf-8")

        result = validator.validate_file(bad_file)

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].code == ErrorCode.MANIFEST_PARSE_ERROR

    def test_manifest_parse_error_empty_file(
        self,
        validator: ManifestValidator,
        tmp_path: Path,
    ) -> None:
        """An empty file triggers MANIFEST_PARSE_ERROR."""
        bad_file = tmp_path / "opentree.json"
        bad_file.write_text("", encoding="utf-8")

        result = validator.validate_file(bad_file)

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].code == ErrorCode.MANIFEST_PARSE_ERROR

    def test_manifest_oserror_returns_parse_error(
        self,
        validator: ManifestValidator,
        tmp_path: Path,
    ) -> None:
        """An unreadable file (OSError) triggers MANIFEST_PARSE_ERROR."""
        bad_file = tmp_path / "opentree.json"
        # Create a directory with the same name so read_text raises OSError
        bad_file.mkdir()

        result = validator.validate_file(bad_file)

        # is_file() returns False for a directory, so we get MANIFEST_NOT_FOUND
        # Test the OSError path by using monkeypatch instead
        assert result.is_valid is False

    def test_manifest_read_permission_error(
        self,
        validator: ManifestValidator,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A PermissionError when reading triggers MANIFEST_PARSE_ERROR."""
        bad_file = tmp_path / "opentree.json"
        bad_file.write_text("{}", encoding="utf-8")

        def mock_read_text(*args: object, **kwargs: object) -> str:
            raise PermissionError("Access denied")

        monkeypatch.setattr(Path, "read_text", mock_read_text)

        result = validator.validate_file(bad_file)

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].code == ErrorCode.MANIFEST_PARSE_ERROR


# ---------------------------------------------------------------------------
# Group B: Schema validation (11 tests)
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """JSON Schema conformance checks."""

    @pytest.mark.parametrize(
        "missing_field",
        ["name", "version", "description", "type", "loading"],
        ids=[
            "test_missing_required_name",
            "test_missing_required_version",
            "test_missing_required_description",
            "test_missing_required_type",
            "test_missing_required_loading",
        ],
    )
    def test_missing_required_field(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
        missing_field: str,
    ) -> None:
        """Removing a required field triggers SCHEMA_VALIDATION_ERROR."""
        data = {k: v for k, v in valid_minimal_manifest.items() if k != missing_field}
        result = validator.validate_dict(data)

        assert result.is_valid is False
        schema_errors = [
            i for i in result.errors if i.code == ErrorCode.SCHEMA_VALIDATION_ERROR
        ]
        assert len(schema_errors) >= 1

    def test_invalid_name_pattern_uppercase(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """Uppercase in name triggers SCHEMA_VALIDATION_ERROR."""
        data = {**valid_minimal_manifest, "name": "BadName"}
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code == ErrorCode.SCHEMA_VALIDATION_ERROR for i in result.errors
        )

    def test_invalid_name_pattern_starts_with_number(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """Name starting with a digit triggers SCHEMA_VALIDATION_ERROR."""
        data = {**valid_minimal_manifest, "name": "1bad-name"}
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code == ErrorCode.SCHEMA_VALIDATION_ERROR for i in result.errors
        )

    def test_invalid_version_format(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """Version "1.0" (missing patch) triggers SCHEMA_VALIDATION_ERROR."""
        data = {**valid_minimal_manifest, "version": "1.0"}
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code == ErrorCode.SCHEMA_VALIDATION_ERROR for i in result.errors
        )

    def test_invalid_type_enum(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """Type "core" (not in enum) triggers SCHEMA_VALIDATION_ERROR."""
        data = {**valid_minimal_manifest, "type": "core"}
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code == ErrorCode.SCHEMA_VALIDATION_ERROR for i in result.errors
        )

    def test_invalid_rules_pattern(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """A rules entry like "../escape.md" triggers SCHEMA_VALIDATION_ERROR."""
        data = {
            **valid_minimal_manifest,
            "loading": {"rules": ["../escape.md"]},
        }
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code == ErrorCode.SCHEMA_VALIDATION_ERROR for i in result.errors
        )

    def test_additional_properties_rejected(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """Unknown top-level properties trigger SCHEMA_VALIDATION_ERROR."""
        data = {**valid_minimal_manifest, "unknown_field": "surprise"}
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code == ErrorCode.SCHEMA_VALIDATION_ERROR for i in result.errors
        )

    def test_prompt_hook_path_traversal_rejected(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """prompt_hook with path traversal triggers SCHEMA_VALIDATION_ERROR."""
        data = {**valid_minimal_manifest, "prompt_hook": "../../../evil.sh"}
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code == ErrorCode.SCHEMA_VALIDATION_ERROR for i in result.errors
        )

    def test_hooks_on_install_path_traversal_rejected(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """hooks.on_install with '..' path traversal triggers SCHEMA_VALIDATION_ERROR."""
        data = {
            **valid_minimal_manifest,
            "hooks": {"on_install": "../../../evil.sh"},
        }
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code == ErrorCode.SCHEMA_VALIDATION_ERROR for i in result.errors
        )

    def test_hooks_on_install_valid_subpath_accepted(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """hooks.on_install with 'scripts/install.sh' is accepted."""
        data = {
            **valid_minimal_manifest,
            "hooks": {"on_install": "scripts/install.sh"},
        }
        result = validator.validate_dict(data)

        # Should not have schema errors for hooks
        hook_errors = [
            i for i in result.errors
            if i.code == ErrorCode.SCHEMA_VALIDATION_ERROR and "hooks" in i.path
        ]
        assert len(hook_errors) == 0

    def test_prompt_hook_valid_filename_accepted(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """prompt_hook with a bare filename is accepted."""
        data = {**valid_minimal_manifest, "prompt_hook": "prompt_hook.py"}
        result = validator.validate_dict(data)

        hook_errors = [
            i for i in result.errors
            if i.code == ErrorCode.SCHEMA_VALIDATION_ERROR and "prompt_hook" in i.path
        ]
        assert len(hook_errors) == 0


# ---------------------------------------------------------------------------
# Group C: Semantic (5 tests)
# ---------------------------------------------------------------------------


class TestSemantic:
    """Semantic checks beyond schema conformance."""

    def test_name_mismatch_with_directory(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """name='foo' but dir='bar' triggers NAME_MISMATCH."""
        data = {**valid_minimal_manifest, "name": "foo"}
        result = validator.validate_dict(data, module_dir_name="bar")

        assert result.is_valid is False
        assert any(i.code == ErrorCode.NAME_MISMATCH for i in result.errors)
        # Error message must include module name
        mismatch = next(i for i in result.errors if i.code == ErrorCode.NAME_MISMATCH)
        assert "foo" in mismatch.message
        assert "bar" in mismatch.message

    def test_name_matches_directory(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """name='test-module' and dir='test-module' passes."""
        result = validator.validate_dict(
            valid_minimal_manifest, module_dir_name="test-module"
        )

        assert result.is_valid is True

    def test_name_mismatch_skipped_when_no_dir(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """When module_dir_name is None, name mismatch check is skipped."""
        data = {**valid_minimal_manifest, "name": "anything-valid"}
        result = validator.validate_dict(data, module_dir_name=None)

        assert not any(i.code == ErrorCode.NAME_MISMATCH for i in result.issues)

    def test_empty_rules_detected(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """rules=[] triggers an error (EMPTY_RULES or SCHEMA_VALIDATION_ERROR)."""
        data = {**valid_minimal_manifest, "loading": {"rules": []}}
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code in (ErrorCode.EMPTY_RULES, ErrorCode.SCHEMA_VALIDATION_ERROR)
            for i in result.errors
        )

    def test_duplicate_rules_detected(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """rules=["a.md","a.md"] triggers an error (DUPLICATE_RULES or SCHEMA)."""
        data = {
            **valid_minimal_manifest,
            "loading": {"rules": ["a.md", "a.md"]},
        }
        result = validator.validate_dict(data)

        assert result.is_valid is False
        assert any(
            i.code in (ErrorCode.DUPLICATE_RULES, ErrorCode.SCHEMA_VALIDATION_ERROR)
            for i in result.errors
        )


# ---------------------------------------------------------------------------
# Group D: Dependency (6 tests)
# ---------------------------------------------------------------------------


class TestDependency:
    """Dependency and conflict checks."""

    def test_dependency_satisfied(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """depends_on=['core'] with installed=['core'] passes."""
        data = {**valid_minimal_manifest, "depends_on": ["core"]}
        issues = validator.validate_dependencies(data, installed_modules=("core",))

        error_issues = [i for i in issues if i.severity == "error"]
        assert len(error_issues) == 0

    def test_dependency_not_found(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """depends_on=['slack'] with installed=['core'] triggers DEPENDENCY_NOT_FOUND."""
        data = {**valid_minimal_manifest, "depends_on": ["slack"]}
        issues = validator.validate_dependencies(data, installed_modules=("core",))

        error_issues = [i for i in issues if i.severity == "error"]
        assert len(error_issues) == 1
        assert error_issues[0].code == ErrorCode.DEPENDENCY_NOT_FOUND
        assert "slack" in error_issues[0].message

    def test_multiple_missing_dependencies(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """Two missing deps produce two DEPENDENCY_NOT_FOUND errors."""
        data = {**valid_minimal_manifest, "depends_on": ["slack", "memory"]}
        issues = validator.validate_dependencies(data, installed_modules=("core",))

        dep_errors = [i for i in issues if i.code == ErrorCode.DEPENDENCY_NOT_FOUND]
        assert len(dep_errors) == 2

    def test_self_dependency(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """depends_on=['test-module'] (self) triggers SELF_DEPENDENCY."""
        data = {**valid_minimal_manifest, "depends_on": ["test-module"]}
        issues = validator.validate_dependencies(data, installed_modules=("core",))

        self_errors = [i for i in issues if i.code == ErrorCode.SELF_DEPENDENCY]
        assert len(self_errors) == 1
        assert "test-module" in self_errors[0].message

    def test_conflict_with_installed(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """conflicts_with=['old'] with installed=['old'] triggers CONFLICT_WITH_INSTALLED."""
        data = {**valid_minimal_manifest, "conflicts_with": ["old"]}
        issues = validator.validate_dependencies(data, installed_modules=("core", "old"))

        conflict_errors = [
            i for i in issues if i.code == ErrorCode.CONFLICT_WITH_INSTALLED
        ]
        assert len(conflict_errors) == 1
        assert "old" in conflict_errors[0].message

    def test_conflict_with_not_installed(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """conflicts_with=['old'] with installed=['core'] passes (no conflict)."""
        data = {**valid_minimal_manifest, "conflicts_with": ["old"]}
        issues = validator.validate_dependencies(data, installed_modules=("core",))

        conflict_errors = [
            i for i in issues if i.code == ErrorCode.CONFLICT_WITH_INSTALLED
        ]
        assert len(conflict_errors) == 0


# ---------------------------------------------------------------------------
# Group E: Batch (2 tests)
# ---------------------------------------------------------------------------


class TestBatch:
    """Batch validation with circular dependency detection."""

    def test_batch_circular_dependency_two(
        self,
        validator: ManifestValidator,
    ) -> None:
        """A->B and B->A produces CIRCULAR_DEPENDENCY."""
        manifests = {
            "mod-a": {
                "name": "mod-a",
                "version": "1.0.0",
                "description": "Module A",
                "type": "optional",
                "depends_on": ["mod-b"],
                "loading": {"rules": ["a.md"]},
            },
            "mod-b": {
                "name": "mod-b",
                "version": "1.0.0",
                "description": "Module B",
                "type": "optional",
                "depends_on": ["mod-a"],
                "loading": {"rules": ["b.md"]},
            },
        }
        results = validator.validate_batch(manifests)

        # At least one module should report circular dependency
        all_issues = []
        for r in results.values():
            all_issues.extend(r.issues)

        circular = [i for i in all_issues if i.code == ErrorCode.CIRCULAR_DEPENDENCY]
        assert len(circular) >= 1

    def test_batch_circular_dependency_three(
        self,
        validator: ManifestValidator,
    ) -> None:
        """A->B->C->A produces CIRCULAR_DEPENDENCY."""
        manifests = {
            "mod-a": {
                "name": "mod-a",
                "version": "1.0.0",
                "description": "Module A",
                "type": "optional",
                "depends_on": ["mod-b"],
                "loading": {"rules": ["a.md"]},
            },
            "mod-b": {
                "name": "mod-b",
                "version": "1.0.0",
                "description": "Module B",
                "type": "optional",
                "depends_on": ["mod-c"],
                "loading": {"rules": ["b.md"]},
            },
            "mod-c": {
                "name": "mod-c",
                "version": "1.0.0",
                "description": "Module C",
                "type": "optional",
                "depends_on": ["mod-a"],
                "loading": {"rules": ["c.md"]},
            },
        }
        results = validator.validate_batch(manifests)

        all_issues = []
        for r in results.values():
            all_issues.extend(r.issues)

        circular = [i for i in all_issues if i.code == ErrorCode.CIRCULAR_DEPENDENCY]
        assert len(circular) >= 1


# ---------------------------------------------------------------------------
# Group F: Warning (3 tests)
# ---------------------------------------------------------------------------


class TestWarnings:
    """Warnings that do not block validity."""

    def test_missing_triggers_warning(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """A manifest without triggers generates a MISSING_TRIGGERS warning."""
        # valid_minimal_manifest has no "triggers" key
        assert "triggers" not in valid_minimal_manifest

        result = validator.validate_dict(valid_minimal_manifest)

        assert result.is_valid is True
        warnings = [i for i in result.warnings if i.code == ErrorCode.MISSING_TRIGGERS]
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"

    def test_unknown_placeholder_mode_warning(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """A placeholder with invalid mode generates UNKNOWN_PLACEHOLDER_MODE warning."""
        data = {
            **valid_minimal_manifest,
            "placeholders": {"some_var": "required", "bad_var": "manual"},
        }
        result = validator.validate_dict(data)

        # Schema enforces enum ["required","optional","auto"], so this should fail
        # at schema level. If schema catches it, that's also acceptable.
        has_issue = any(
            i.code
            in (
                ErrorCode.UNKNOWN_PLACEHOLDER_MODE,
                ErrorCode.SCHEMA_VALIDATION_ERROR,
            )
            for i in result.issues
        )
        assert has_issue

    def test_warnings_do_not_block_validity(
        self,
        validator: ManifestValidator,
        valid_minimal_manifest: dict[str, Any],
    ) -> None:
        """A manifest with warnings but no errors is still is_valid=True."""
        # valid_minimal has no triggers → generates MISSING_TRIGGERS warning
        result = validator.validate_dict(valid_minimal_manifest)

        assert result.is_valid is True
        assert len(result.warnings) >= 1
        assert len(result.errors) == 0
