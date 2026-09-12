"""Provider control values are strict; secrets have a separate write-only wire."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from commerce_eval.core.redaction import contains_secret, redact_text

PRESETS = (
    {"provider_id": "deepseek", "kind": "deepseek", "name": "DeepSeek",
     "base_url": "https://api.deepseek.com", "model": "deepseek-chat",
     "credential_env": "DEEPSEEK_API_KEY"},
    {"provider_id": "laozhang", "kind": "laozhang", "name": "LaoZhang API",
     "base_url": "https://api.laozhang.ai/v1", "model": "",
     "credential_env": "LAOZHANG_API_KEY"},
    {"provider_id": "custom", "kind": "custom", "name": "Custom compatible provider",
     "base_url": "", "model": "", "credential_env": "CUSTOM_API_KEY"},
)


class ProviderWire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProviderSave(ProviderWire):
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,119}$")
    kind: Literal["deepseek", "laozhang", "custom"] = "custom"
    name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=1, max_length=1000)
    model: str = Field(default="", max_length=160)
    credential_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,110}_API_KEY$")
    enabled: bool = True
    allow_localhost: bool = False
    endpoint_confirmed: bool = False
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("provider_id", "name", "model", "credential_env", "base_url")
    @classmethod
    def public_text(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("provider_config_invalid")
        if contains_secret(value) or redact_text(value) != value:
            raise ValueError("provider_config_secret_rejected")
        return value.strip()

    @model_validator(mode="after")
    def preset_identity(self):
        for preset in PRESETS[:2]:
            if self.provider_id == preset["provider_id"] and self.kind != preset["kind"]:
                raise ValueError("provider_preset_invalid")
            if self.kind == preset["kind"] and self.credential_env != preset["credential_env"]:
                raise ValueError("provider_preset_invalid")
        if not self.name:
            raise ValueError("provider_config_invalid")
        return self


class CredentialSave(ProviderWire):
    version: int = Field(ge=1)
    secret: SecretStr = Field(min_length=1, max_length=4096)
    expected_env_version: str = Field(min_length=1, max_length=100)
    acknowledge_shared: bool = False


class ProviderCheck(ProviderWire):
    version: int = Field(ge=1)
    allow_paid: bool = False
    model: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("model")
    @classmethod
    def model_name(cls, value):
        if value is not None:
            return ProviderSave.public_text(value)
        return value
