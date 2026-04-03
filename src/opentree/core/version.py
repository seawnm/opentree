"""Semantic version comparison utilities.

Uses pure-Python tuple comparison — no external dependencies.
Supports standard semver format: MAJOR.MINOR.PATCH (e.g. "1.2.3").
"""

from __future__ import annotations


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple.

    Args:
        version_str: A dot-separated version string (e.g. "1.2.3").

    Returns:
        Tuple of integers (e.g. (1, 2, 3)).

    Raises:
        ValueError: If the version string contains non-numeric parts.
    """
    if not version_str or not version_str.strip():
        raise ValueError(f"Empty version string: {version_str!r}")

    parts = version_str.strip().split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        raise ValueError(
            f"Invalid version string: {version_str!r} "
            f"(all parts must be integers)"
        ) from None


def compare_versions(installed: str, bundled: str) -> int:
    """Compare two version strings.

    Args:
        installed: Currently installed version.
        bundled: Available bundled version.

    Returns:
        -1 if installed < bundled (upgrade available)
         0 if installed == bundled (up to date)
         1 if installed > bundled (downgrade would be needed)
    """
    v_installed = parse_version(installed)
    v_bundled = parse_version(bundled)

    if v_installed < v_bundled:
        return -1
    elif v_installed == v_bundled:
        return 0
    else:
        return 1
