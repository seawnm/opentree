"""Tests for the OpenTree JSON Schema definition.

Verifies that the schema file itself is valid and well-formed.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema


SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "opentree"
    / "schema"
    / "opentree.schema.json"
)


class TestSchemaIntegrity:
    """Tests that the schema file is a valid JSON Schema."""

    def test_schema_file_exists_and_parseable(self) -> None:
        """The schema file must exist and contain valid JSON."""
        assert SCHEMA_PATH.exists(), f"Schema file not found at {SCHEMA_PATH}"

        raw = SCHEMA_PATH.read_text(encoding="utf-8")
        schema = json.loads(raw)

        assert isinstance(schema, dict), "Schema root must be a JSON object"
        assert "properties" in schema, "Schema must define properties"
        assert "required" in schema, "Schema must define required fields"

    def test_schema_is_valid_json_schema(self) -> None:
        """The schema must be a valid JSON Schema (draft-2020-12)."""
        raw = SCHEMA_PATH.read_text(encoding="utf-8")
        schema = json.loads(raw)

        # jsonschema.validators.validator_for resolves the correct meta-schema
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
