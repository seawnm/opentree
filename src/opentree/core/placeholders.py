"""Placeholder resolution engine for OpenTree module rules.

Resolves ``{{key}}`` placeholders in rule template files using values
from ``UserConfig``.  Files with no placeholders pass through unchanged.

Design:
    - Templates use ``{{key}}`` syntax (double-brace Mustache-like).
    - Each manifest may declare ``placeholders`` with mode per key
      (``required``, ``optional``, ``auto``) so that ``install`` can
      validate before linking.
    - Resolution produces a *copy* (``resolved_copy``) rather than a symlink
      so that the target contains concrete values.
    - Uses a single-pass regex (``re.sub``) to resolve only *known*
      placeholders in one sweep, preventing double-replacement when
      a resolved value itself contains ``{{...}}`` syntax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from opentree.core.config import UserConfig


@dataclass(frozen=True)
class ResolveResult:
    """Outcome of resolving placeholders in a single file.

    Immutable.
    """

    source: str
    target: str
    had_placeholders: bool
    unresolved: tuple[str, ...] = ()


class PlaceholderEngine:
    """Resolve ``{{key}}`` placeholders using a ``UserConfig``.

    Args:
        config: The user configuration supplying placeholder values.
    """

    def __init__(self, config: UserConfig) -> None:
        self._config = config
        self._replacements: dict[str, str] = {
            "{{bot_name}}": config.bot_name or "OpenTree",
            "{{team_name}}": config.team_name,
            "{{admin_channel}}": config.admin_channel,
            "{{owner_description}}": config.owner_description,
            "{{admin_description}}": config.owner_description,  # backward compat alias
            "{{opentree_home}}": config.opentree_home.replace("\\", "/"),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def replacements(self) -> dict[str, str]:
        """Return a copy of the current replacement map."""
        return dict(self._replacements)

    def resolve_content(self, content: str) -> str:
        """Replace only known ``{{key}}`` tokens in *content*.

        Uses a single-pass regex replacement so that resolved values
        containing ``{{...}}`` syntax are never subject to further
        expansion (no double-replacement risk).  Unknown ``{{key}}``
        tokens are left as-is.
        """

        def _replace_match(match: re.Match[str]) -> str:
            token = match.group(0)  # e.g. "{{bot_name}}"
            if token in self._replacements:
                return self._replacements[token]
            return token  # leave unknown tokens untouched

        return re.sub(r"\{\{[^}]*\}\}", _replace_match, content)

    def resolve_file(self, source: Path, target: Path) -> ResolveResult:
        """Read *source*, resolve placeholders, write result to *target*.

        Only writes *target* when the content actually contains
        placeholders.  Parent directories of *target* are created
        automatically.

        Returns:
            A ``ResolveResult`` describing what happened.
        """
        content = source.read_text(encoding="utf-8")
        resolved = self.resolve_content(content)
        had = content != resolved
        unresolved = self.scan_unresolved(resolved)

        if had:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(resolved, encoding="utf-8")

        return ResolveResult(
            source=str(source),
            target=str(target),
            had_placeholders=had,
            unresolved=unresolved,
        )

    def has_placeholders(self, content: str) -> bool:
        """Return *True* if *content* contains any known placeholder."""
        return any(p in content for p in self._replacements)

    def scan_unresolved(self, content: str) -> tuple[str, ...]:
        """Find ``{{key}}`` tokens in *content* that are not in the map.

        Returns:
            Tuple of unknown placeholder strings (e.g. ``{{foo}}``).
        """
        found = re.findall(r"\{\{[a-z_]+\}\}", content)
        known = set(self._replacements.keys())
        return tuple(p for p in found if p not in known)

    def validate_module_placeholders(
        self,
        manifest_placeholders: dict[str, str],
    ) -> list[str]:
        """Check that required placeholders have non-empty values.

        ``manifest_placeholders`` maps placeholder names to their mode::

            {"bot_name": "required", "team_name": "optional", "opentree_home": "auto"}

        Only ``required`` mode triggers an error when the value is empty.

        Returns:
            A list of error messages (empty means all OK).
        """
        errors: list[str] = []
        for name, mode in manifest_placeholders.items():
            placeholder = f"{{{{{name}}}}}"
            value = self._replacements.get(placeholder, "")
            if mode == "required" and not value.strip():
                errors.append(
                    f"Required placeholder '{name}' has no value in config"
                )
        return errors
