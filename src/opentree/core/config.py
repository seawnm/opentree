"""User-level configuration for an OpenTree instance.

Loads configuration from ``config/user.json`` under the OpenTree home
directory. Falls back to sensible defaults when the file is missing or
fields are omitted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UserConfig:
    """User-level configuration for an OpenTree instance.

    All fields are immutable (frozen dataclass).
    ``opentree_home`` is always set from the caller-provided path,
    never from the JSON file.
    """

    bot_name: str = "OpenTree"
    team_name: str = ""
    admin_channel: str = ""
    admin_description: str = ""
    opentree_home: str = ""


def load_user_config(opentree_home: Path) -> UserConfig:
    """Load user config from ``config/user.json``.

    Returns defaults if the file is missing or fields are omitted.
    ``opentree_home`` is always derived from the *parameter*, not the file.

    Args:
        opentree_home: Root directory of the OpenTree installation.

    Returns:
        A frozen UserConfig instance.
    """
    config_path = opentree_home / "config" / "user.json"
    if not config_path.exists():
        return UserConfig(opentree_home=str(opentree_home))

    data = json.loads(config_path.read_text(encoding="utf-8"))
    return UserConfig(
        bot_name=data.get("bot_name", "OpenTree"),
        team_name=data.get("team_name", ""),
        admin_channel=data.get("admin_channel", ""),
        admin_description=data.get("admin_description", ""),
        opentree_home=str(opentree_home),
    )
