from typing import Literal

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


class ResourceSettings(BaseModel):
    max_execution_timeout_secs: int = 300
    max_output_bytes: int = 1_048_576  # 1 MiB


class DevSpaceSettings(BaseSettings):
    """
    Structured Configuration Management (ADR-007).
    Runtime settings are loaded from DEV_SPACE_* environment variables, then
    model defaults. Repository control-plane policy is loaded separately.
    """

    core: CoreSettings = Field(default_factory=CoreSettings)
    identity_human: IdentitySettings = Field(default_factory=IdentitySettings)
    identity_agent: IdentitySettings = Field(default_factory=IdentitySettings)
    resources: ResourceSettings = Field(default_factory=ResourceSettings)

    model_config = SettingsConfigDict(
        env_prefix="DEV_SPACE_",
        env_nested_delimiter="__",
    )

    @classmethod
    def load(cls) -> "DevSpaceSettings":
        return cls()


config = DevSpaceSettings.load()
