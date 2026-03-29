"""Manages .claude/rules/ symlinks for installed modules.

Handles creating, removing, reconciling, and verifying symlinks
(or fallback copies) that wire module rule files into the workspace.

Fallback chain: symlink -> junction (NTFS, dir-only) -> copy.
The chosen method is persisted in RegistryEntry.link_method so that
remove/update can branch on it correctly.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class LinkResult:
    """Result of a single link operation.

    Immutable — never modified after creation.
    """

    source: str
    target: str
    method: str  # "symlink" | "junction" | "copy"
    success: bool
    error: str = ""


class SymlinkManager:
    """Manages .claude/rules/ symlinks for installed modules.

    Each module's rule files are linked (or copied) into
    ``<workspace>/.claude/rules/<module_name>/``.
    """

    def __init__(self, opentree_home: Path) -> None:
        self._home = opentree_home
        self._rules_dir = opentree_home / "workspace" / ".claude" / "rules"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_module_links(
        self, module_name: str, rules: Sequence[str]
    ) -> tuple[LinkResult, ...]:
        """Create symlinks (or fallback copies) for a module's rules.

        Returns tuple of LinkResult for each rule file.
        All rules use the same link method (determined by first attempt).

        Raises:
            FileNotFoundError: If a source rule file does not exist.
            ValueError: If module_name contains invalid characters.
        """
        if not re.match(r'^[a-z]([a-z0-9-]*[a-z0-9])?$', module_name):
            raise ValueError(f"Invalid module name: {module_name}")

        source_dir = self._home / "modules" / module_name / "rules"
        target_dir = self._rules_dir / module_name
        target_dir.mkdir(parents=True, exist_ok=True)

        # Validate all sources exist before creating any links
        sources: list[Path] = []
        for rule_name in rules:
            src = source_dir / rule_name
            if not src.exists():
                msg = f"Rule file not found: {src} ({rule_name})"
                raise FileNotFoundError(msg)
            sources.append(src)

        results: list[LinkResult] = []
        determined_method: str | None = None

        for src, rule_name in zip(sources, rules):
            tgt = target_dir / rule_name
            absolute_source = src.resolve()

            if determined_method is None:
                # First file: try full fallback chain to determine method
                result = self._create_link(absolute_source, tgt)
                determined_method = result.method
            elif determined_method == "symlink":
                result = self._try_symlink(absolute_source, tgt)
            elif determined_method == "junction":
                result = self._try_junction(absolute_source, tgt)
            else:
                result = self._try_copy(absolute_source, tgt)

            results.append(result)

        return tuple(results)

    def remove_module_links(
        self, module_name: str, link_method: str = "symlink"
    ) -> None:
        """Remove a module's rules from .claude/rules/.

        Preserves non-symlink user files in .trash/ before removal.
        Branches on link_method for correct cleanup.
        Idempotent: does nothing if the module dir does not exist.
        """
        target_dir = self._rules_dir / module_name
        if not target_dir.exists():
            return

        # Preserve user files before removal
        self._preserve_user_files(target_dir, module_name)

        # Remove the module directory
        if link_method == "symlink":
            # Unlink individual symlinks, then remove dir
            for item in target_dir.iterdir():
                if item.is_symlink():
                    item.unlink()
                else:
                    item.unlink()
            target_dir.rmdir()
        else:
            # junction or copy: rmtree handles everything
            shutil.rmtree(target_dir)

    def reconcile_all(
        self, module_rules: dict[str, Sequence[str]]
    ) -> dict[str, tuple[LinkResult, ...]]:
        """Full teardown + rebuild of all symlinks.

        Removes any module directories under .claude/rules/ that are NOT
        in ``module_rules``, then creates fresh links for all modules.

        Args:
            module_rules: ``{module_name: [rule_filenames]}``.

        Returns:
            ``{module_name: tuple[LinkResult, ...]}`` for each module.
        """
        # Teardown: remove stale module directories
        if self._rules_dir.exists():
            for child in self._rules_dir.iterdir():
                if child.is_dir() and child.name not in module_rules:
                    # Skip .trash directory
                    if child.name == ".trash":
                        continue
                    self.remove_module_links(child.name)

        # Also remove current modules (full rebuild)
        for module_name in module_rules:
            target_dir = self._rules_dir / module_name
            if target_dir.exists():
                self.remove_module_links(module_name)

        # Rebuild
        results: dict[str, tuple[LinkResult, ...]] = {}
        for module_name, rules in module_rules.items():
            results[module_name] = self.create_module_links(module_name, rules)

        return results

    def verify(self) -> list[str]:
        """Return list of broken symlink paths under .claude/rules/.

        Checks all symlinks recursively. Non-symlink files are ignored.
        """
        broken: list[str] = []
        if not self._rules_dir.exists():
            return broken

        for item in self._rules_dir.rglob("*"):
            if item.is_symlink() and not item.resolve().exists():
                broken.append(str(item))

        return broken

    # ------------------------------------------------------------------
    # Link creation methods (private)
    # ------------------------------------------------------------------

    def _try_symlink(self, source: Path, target: Path) -> LinkResult:
        """Try os.symlink. Returns LinkResult."""
        try:
            os.symlink(source, target)
            return LinkResult(
                source=str(source),
                target=str(target),
                method="symlink",
                success=True,
            )
        except OSError as exc:
            return LinkResult(
                source=str(source),
                target=str(target),
                method="symlink",
                success=False,
                error=str(exc),
            )

    def _try_junction(self, source: Path, target: Path) -> LinkResult:
        """Try NTFS junction via cmd.exe. Returns LinkResult.

        Junctions only work for directories on NTFS. For files or when
        cmd.exe is unavailable, this returns a failure result.
        """
        if not source.is_dir():
            return LinkResult(
                source=str(source),
                target=str(target),
                method="junction",
                success=False,
                error="Junction only supports directories",
            )

        try:
            result = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(target), str(source)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return LinkResult(
                    source=str(source),
                    target=str(target),
                    method="junction",
                    success=True,
                )
            return LinkResult(
                source=str(source),
                target=str(target),
                method="junction",
                success=False,
                error=result.stderr.strip(),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            return LinkResult(
                source=str(source),
                target=str(target),
                method="junction",
                success=False,
                error=str(exc),
            )

    def _try_copy(self, source: Path, target: Path) -> LinkResult:
        """Copy file or directory. Returns LinkResult."""
        try:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            return LinkResult(
                source=str(source),
                target=str(target),
                method="copy",
                success=True,
            )
        except OSError as exc:
            return LinkResult(
                source=str(source),
                target=str(target),
                method="copy",
                success=False,
                error=str(exc),
            )

    def _create_link(self, source: Path, target: Path) -> LinkResult:
        """Try symlink -> junction -> copy fallback chain.

        Returns the first successful LinkResult.
        """
        # 1. Try symlink
        result = self._try_symlink(source, target)
        if result.success:
            return result

        # 2. Try junction (directory only, skip if cmd.exe unavailable)
        result = self._try_junction(source, target)
        if result.success:
            return result

        # 3. Fallback to copy
        return self._try_copy(source, target)

    # ------------------------------------------------------------------
    # User file preservation (private)
    # ------------------------------------------------------------------

    def _preserve_user_files(
        self, module_dir: Path, module_name: str
    ) -> list[str]:
        """Move non-symlink user files to .trash/. Returns preserved paths.

        Scans the module directory for files that are neither symlinks
        nor part of the expected module rules. These are assumed to be
        user-created and are preserved in ``.trash/<module_name>/``.
        """
        preserved: list[str] = []
        if not module_dir.exists():
            return preserved

        trash_dir = self._rules_dir / ".trash" / module_name

        for item in module_dir.iterdir():
            # Skip symlinks — those are managed by us
            if item.is_symlink():
                continue
            # Non-symlink files are user files; preserve them
            if item.is_file():
                trash_dir.mkdir(parents=True, exist_ok=True)
                dest = trash_dir / item.name
                shutil.move(str(item), str(dest))
                preserved.append(str(dest))

        return preserved
