"""Generates CLAUDE.md from registry + module manifests.

The generated file serves as a lightweight index for the workspace.
All module rules are loaded via ``.claude/rules/`` symlinks — CLAUDE.md
only provides an overview of installed modules and their triggers.

Path normalisation: all paths in the output use forward slashes,
even on Windows, for consistent display.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from opentree.core.config import UserConfig
from opentree.registry.models import RegistryData


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
        content = gen.generate(opentree_home, registry, config)
        (opentree_home / "workspace" / "CLAUDE.md").write_text(content)
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

        Uses ``str.replace()`` (not ``re.sub``) to avoid backslash
        interpretation issues with Windows paths.
        """
        replacements = {
            "{{bot_name}}": config.bot_name or "OpenTree",
            "{{team_name}}": config.team_name,
            "{{admin_channel}}": config.admin_channel,
            "{{opentree_home}}": config.opentree_home.replace("\\", "/"),
        }
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        return content
