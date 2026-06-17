import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseModel):
    default_lane: Literal["human", "agent"] = "agent"
    default_format: Literal["json", "jsonl", "md"] = "jsonl"
    log_level: Literal["debug", "info", "warn", "error"] = "info"
    log_target: Literal["file", "endpoint"] = "file"
    log_endpoint: str = ""


class IdentitySettings(BaseModel):
    name: str = ""
    email: str = ""
    ssh_host: str = ""


class DaemonSettings(BaseModel):
    log_compression_hour_utc: int = 0
    log_retention_days: int = 30
    session_reap_interval_hours: int = 6


class ResourceSettings(BaseModel):
    max_execution_timeout_secs: int = 300
    max_output_bytes: int = 1_048_576  # 1 MiB


class DevSpaceSettings(BaseSettings):
    """
    Structured Configuration Management (ADR-007).
    Hierarchy: CLI Flags -> Env Vars -> Project Config -> User Config -> Defaults
    """

    core: CoreSettings = Field(default_factory=CoreSettings)
    identity_human: IdentitySettings = Field(default_factory=IdentitySettings)
    identity_agent: IdentitySettings = Field(default_factory=IdentitySettings)
    daemon: DaemonSettings = Field(default_factory=DaemonSettings)
    resources: ResourceSettings = Field(default_factory=ResourceSettings)

    model_config = SettingsConfigDict(
        env_prefix="DEV_SPACE_",
        env_nested_delimiter="__",
    )

    @classmethod
    def load(cls) -> "DevSpaceSettings":
        # Pydantic Settings handles env vars automatically.
        # We can layer TOML files here. For simplicity in Phase 1, we rely on env vars + defaults.
        # TODO: Add TOML file reading from ~/.config/dev-space/config.toml
        return cls()

config = DevSpaceSettings.load()
