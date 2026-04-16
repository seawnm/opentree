"""Generates CLAUDE.md from registry + module manifests.

The generated file serves as a lightweight index for the workspace.
All module rules are loaded via ``.claude/rules/`` symlinks — CLAUDE.md
only provides an overview of installed modules and their triggers.

Path normalisation: all paths in the output use forward slashes,
even on Windows, for consistent display.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from opentree.core.config import UserConfig
from opentree.registry.models import RegistryData

logger = logging.getLogger(__name__)

_AUTO_BEGIN = "<!-- OPENTREE:AUTO:BEGIN -->"
_AUTO_END = "<!-- OPENTREE:AUTO:END -->"
_OWNER_HINT = "\n<!-- 以下為 Owner 自訂區塊，module 安裝/更新/refresh 不會覆蓋 -->\n"
_AGENTS_AUTO_BEGIN = "# OPENTREE:AUTO:BEGIN"
_AGENTS_AUTO_END = "# OPENTREE:AUTO:END"
_AGENTS_OWNER_HINT = "# (auto-generated — edit below this line)\n"


@dataclass(frozen=True)
class ModuleInfo:
    """Extracted module info for CLAUDE.md rendering.

    Immutable snapshot of the fields we need from each manifest.
    """

    name: str
    version: str
    description: str
    trigger_keywords: tuple[str, ...] = ()
    trigger_description: str = ""


class ClaudeMdGenerator:
    """Generates CLAUDE.md content from registry + module manifests.

    Usage::

        gen = ClaudeMdGenerator()
        # For new files, always wrap with markers:
        content = gen.wrap_with_markers(gen.generate(home, registry, config))
        # For re-generation preserving owner content:
        content = gen.generate_with_preservation(existing, home, registry, config)
        (home / "workspace" / "CLAUDE.md").write_text(content)
    """

    def generate(
        self,
        opentree_home: Path,
        registry: RegistryData,
        config: UserConfig,
    ) -> str:
        """Generate CLAUDE.md content.

        Args:
            opentree_home: Root directory of the OpenTree installation.
            registry: Current registry state (must be non-empty).
            config: User-level configuration.

        Returns:
            The complete CLAUDE.md content as a string.

        Raises:
            RuntimeError: If registry is empty (no modules installed).
        """
        if not registry.modules:
            raise RuntimeError(
                "Registry is empty \u2014 run 'opentree init' to install modules first"
            )

        modules = self._load_module_infos(opentree_home, registry)

        sections: list[str] = []
        sections.extend(self._render_header(config))
        sections.extend(self._render_paths(config))
        sections.extend(self._render_module_list(modules))
        sections.extend(self._render_trigger_table(modules))
        sections.extend(self._render_notes())

        content = "\n".join(sections) + "\n"
        return self._substitute_placeholders(content, config)

    # ------------------------------------------------------------------
    # Marker wrapping and preservation
    # ------------------------------------------------------------------

    def wrap_with_markers(self, content: str) -> str:
        """Wrap generated content with AUTO markers and owner hint.

        Args:
            content: The raw output from ``generate()``.

        Returns:
            Content wrapped with BEGIN/END markers and an owner hint.
        """
        return f"{_AUTO_BEGIN}\n{content}\n{_AUTO_END}\n{_OWNER_HINT}"

    def generate_with_preservation(
        self,
        existing_content: str | None,
        home: Path,
        registry: RegistryData,
        config: UserConfig,
    ) -> str:
        """Generate CLAUDE.md while preserving owner-written content.

        Args:
            existing_content: Current CLAUDE.md text, or None for a new file.
            home: Root directory of the OpenTree installation.
            registry: Current registry state.
            config: User-level configuration.

        Returns:
            The merged CLAUDE.md content.
        """
        auto_content = self.wrap_with_markers(
            self.generate(home, registry, config)
        )

        if existing_content is None:
            return auto_content

        begin_idx = existing_content.find(_AUTO_BEGIN)
        # Find the END marker that follows the BEGIN marker
        # (not one embedded in owner content)
        if begin_idx != -1:
            end_idx = existing_content.find(_AUTO_END, begin_idx)
        else:
            end_idx = -1

        if begin_idx == -1 or end_idx == -1:
            # Missing marker(s) (legacy migration) — entire old file is owner content
            logger.warning(
                "CLAUDE.md has no AUTO markers, treating entire content as owner content"
            )
            return auto_content + "\n" + existing_content

        # Extract everything after the END marker
        owner_content = existing_content[end_idx + len(_AUTO_END) :]
        # Remove owner hint to avoid duplication
        owner_content = owner_content.replace(_OWNER_HINT, "")

        if owner_content.strip():
            return auto_content + "\n" + owner_content
        else:
            return auto_content

    # ------------------------------------------------------------------
    # Module info extraction
    # ------------------------------------------------------------------

    def _load_module_infos(
        self, opentree_home: Path, registry: RegistryData
    ) -> list[ModuleInfo]:
        """Load manifest metadata for all registered modules.

        Skips modules whose manifest file is missing on disk.
        """
        infos: list[ModuleInfo] = []
        for name, entry in registry.modules:
            manifest_path = opentree_home / "modules" / name / "opentree.json"
            if not manifest_path.exists():
                continue  # Will be caught by verify command
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            triggers = data.get("triggers", {})
            infos.append(
                ModuleInfo(
                    name=name,
                    version=data.get("version", entry.version),
                    description=data.get("description", ""),
                    trigger_keywords=tuple(triggers.get("keywords", [])),
                    trigger_description=triggers.get("description", ""),
                )
            )
        return infos

    # ------------------------------------------------------------------
    # Section renderers
    # ------------------------------------------------------------------

    def _render_header(self, config: UserConfig) -> list[str]:
        """Render the top-level heading and intro note."""
        bot = config.bot_name or "OpenTree"
        return [
            f"# {bot} \u7684\u5de5\u4f5c\u5340",
            "",
            "> \u6a21\u7d44 rules \u5df2\u900f\u904e .claude/rules/ "
            "\u81ea\u52d5\u8f09\u5165\uff0c"
            "\u672c\u6587\u4ef6\u50c5\u70ba\u7d22\u5f15\u3002",
            "",
        ]

    def _render_paths(self, config: UserConfig) -> list[str]:
        """Render the path conventions section with forward-slash normalisation."""
        home = config.opentree_home.replace("\\", "/")
        return [
            "## \u8def\u5f91\u6163\u4f8b",
            "",
            f"- `$OPENTREE_HOME` = `{home}`",
            "- \u6a21\u7d44\u76ee\u9304\uff1a`$OPENTREE_HOME/modules/`",
            "- \u5de5\u4f5c\u5340\u76ee\u9304\uff1a`$OPENTREE_HOME/workspace/`",
            "- \u8cc7\u6599\u76ee\u9304\uff1a`$OPENTREE_HOME/data/`",
            "",
        ]

    def _render_module_list(self, modules: list[ModuleInfo]) -> list[str]:
        """Render the installed modules list."""
        lines = [
            "## \u5df2\u5b89\u88dd\u6a21\u7d44",
            "",
        ]
        for mod in modules:
            lines.append(
                f"- **{mod.name}** (v{mod.version}) \u2014 {mod.description}"
            )
        lines.append("")
        return lines

    def _render_trigger_table(self, modules: list[ModuleInfo]) -> list[str]:
        """Render the trigger index table.

        Uses em dash (\u2014) for modules without triggers.
        """
        lines = [
            "## \u6a21\u7d44\u89f8\u767c\u7d22\u5f15",
            "",
            "| \u6a21\u7d44 | \u89f8\u767c\u95dc\u9375\u5b57 | \u8aaa\u660e |",
            "|------|-----------|------|",
        ]
        for mod in modules:
            keywords = (
                ", ".join(mod.trigger_keywords)
                if mod.trigger_keywords
                else "\u2014"
            )
            desc = mod.trigger_description or "\u2014"
            lines.append(f"| {mod.name} | {keywords} | {desc} |")
        lines.append("")
        return lines

    def _render_notes(self) -> list[str]:
        """Render the notes section."""
        return [
            "## \u6ce8\u610f\u4e8b\u9805",
            "",
            "- \u6240\u6709\u6a21\u7d44 rules "
            "\u5df2\u81ea\u52d5\u8f09\u5165\uff08.claude/rules/\uff09\uff0c"
            "\u4e0d\u9700\u8981\u624b\u52d5 Read",
            "- \u4fee\u6539 config \u5f8c\u9700\u57f7\u884c "
            "`opentree refresh`",
            "- .env \u4e0d\u7d0d\u5165\u7248\u63a7\uff0c"
            "\u5305\u542b\u654f\u611f Token",
        ]

    # ------------------------------------------------------------------
    # Placeholder substitution
    # ------------------------------------------------------------------

    def _substitute_placeholders(self, content: str, config: UserConfig) -> str:
        """Replace ``{{...}}`` placeholders with actual values.

        Delegates to ``PlaceholderEngine`` for consistent resolution
        across the entire codebase.
        """
        from opentree.core.placeholders import PlaceholderEngine

        engine = PlaceholderEngine(config)
        return engine.resolve_content(content)


def generate_agents_md(
    opentree_home: Path,
    registry: RegistryData,
    config: UserConfig,
    existing_content: str | None = None,
) -> str:
    """Generate AGENTS.md content for Codex CLI.

    AGENTS.md is Codex's equivalent of CLAUDE.md — it is read as the
    agent instructions file. The content body matches CLAUDE.md but uses
    plain ``# OPENTREE:AUTO:BEGIN`` / ``# OPENTREE:AUTO:END`` markers.
    """
    generator = ClaudeMdGenerator()
    auto_content = _wrap_agents_markers(
        generator.generate(opentree_home, registry, config)
    )

    if existing_content is None:
        return auto_content

    begin_idx = existing_content.find(_AGENTS_AUTO_BEGIN)
    end_idx = (
        existing_content.find(_AGENTS_AUTO_END, begin_idx)
        if begin_idx != -1
        else -1
    )

    if begin_idx == -1 or end_idx == -1:
        logger.warning(
            "AGENTS.md has no AUTO markers, treating entire content as owner content"
        )
        return auto_content + "\n" + existing_content

    owner_content = existing_content[end_idx + len(_AGENTS_AUTO_END) :]
    owner_content = owner_content.replace(_AGENTS_OWNER_HINT, "")

    if owner_content.strip():
        return auto_content + "\n" + owner_content
    return auto_content


def _wrap_agents_markers(content: str) -> str:
    """Wrap generated AGENTS.md content with Codex-compatible markers."""
    return (
        f"{_AGENTS_AUTO_BEGIN}\n"
        f"{content}\n"
        f"{_AGENTS_AUTO_END}\n"
        f"{_AGENTS_OWNER_HINT}"
    )
