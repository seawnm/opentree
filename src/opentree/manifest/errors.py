"""Error codes for manifest validation.

Each error code represents a specific validation failure. Codes are grouped
by category: structural errors, schema errors, semantic errors, dependency
errors, and warnings.
"""

from enum import Enum, unique


@unique
class ErrorCode(Enum):
    """Enumeration of all manifest validation error codes.

    Attributes:
        MANIFEST_NOT_FOUND: The opentree.json file does not exist.
        MANIFEST_PARSE_ERROR: The file is not valid JSON.
        SCHEMA_VALIDATION_ERROR: The manifest does not conform to the JSON Schema.
        NAME_MISMATCH: The name field does not match the module directory name.
        DEPENDENCY_NOT_FOUND: A depends_on entry references a non-existent module.
        CIRCULAR_DEPENDENCY: The dependency graph contains a cycle.
        SELF_DEPENDENCY: A module lists itself in depends_on.
        CONFLICT_WITH_INSTALLED: A conflicts_with entry matches an installed module.
        MISSING_TRIGGERS: The manifest has no triggers section (warning).
        RULE_FILENAME_COLLISION: Two modules share the same rule filename.
    """

    # Structural errors
    MANIFEST_NOT_FOUND = "MANIFEST_NOT_FOUND"
    MANIFEST_PARSE_ERROR = "MANIFEST_PARSE_ERROR"

    # Schema errors
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"

    # Semantic errors
    NAME_MISMATCH = "NAME_MISMATCH"

    # Dependency errors
    DEPENDENCY_NOT_FOUND = "DEPENDENCY_NOT_FOUND"
    CIRCULAR_DEPENDENCY = "CIRCULAR_DEPENDENCY"
    SELF_DEPENDENCY = "SELF_DEPENDENCY"
    CONFLICT_WITH_INSTALLED = "CONFLICT_WITH_INSTALLED"

    # Batch errors
    RULE_FILENAME_COLLISION = "RULE_FILENAME_COLLISION"

    # Warnings
    MISSING_TRIGGERS = "MISSING_TRIGGERS"
