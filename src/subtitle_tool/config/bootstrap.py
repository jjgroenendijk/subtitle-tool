"""Bootstrap settings sourced from environment variables only.

These cover container bootstrap concerns (port, config directory, file ownership,
timezone). Everything else lives in the persisted config file edited through the
web UI; see ``subtitle_tool.config.models``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BootstrapSettings(BaseSettings):
    """Container bootstrap settings read from the environment.

    Field names map to environment variables directly (``CONFIG_DIR``, ``PORT``,
    ``PUID``, ``PGID``, ``TZ``); the lookup is case-insensitive.
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    config_dir: Path = Field(
        default=Path("/config"),
        validation_alias="CONFIG_DIR",
        description="Directory holding the config file and SQLite job history.",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        validation_alias="PORT",
        description="TCP port the web UI listens on.",
    )
    puid: int = Field(
        default=1000,
        ge=0,
        validation_alias="PUID",
        description="User id that written files are owned by.",
    )
    pgid: int = Field(
        default=1000,
        ge=0,
        validation_alias="PGID",
        description="Group id that written files are owned by.",
    )
    tz: str = Field(
        default="UTC",
        validation_alias="TZ",
        description="Timezone name used for scheduling and timestamps.",
    )

    @property
    def config_file(self) -> Path:
        """Path to the persisted configuration file inside ``config_dir``."""
        return self.config_dir / "config.toml"


def load_bootstrap() -> BootstrapSettings:
    """Read bootstrap settings from the current environment."""
    return BootstrapSettings()
