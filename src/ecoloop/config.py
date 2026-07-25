from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    energyplus_home: Path = (
        PROJECT_ROOT
        / ".local"
        / "EnergyPlus-26.1.0"
        / "EnergyPlus-26.1.0-6f2e40d102-Windows-x86_64"
    )
    ecoloop_idf: Path = PROJECT_ROOT / "models" / "baseline" / "small_office.idf"
    ecoloop_epw: Path = PROJECT_ROOT / "models" / "weather" / "bengaluru.epw"
    llm_base_url: str = Field(
        default="http://localhost:11434/v1",
        validation_alias="ECOLOOP_LLM_BASE_URL",
    )
    llm_api_key: str = Field(
        default="ollama",
        validation_alias="ECOLOOP_LLM_API_KEY",
        repr=False,
    )
    llm_model: str = Field(
        default="llama3.1:8b",
        validation_alias="ECOLOOP_LLM_MODEL",
    )
    ecoloop_reason_enabled: bool = True
    ecoloop_reason_interval_minutes: int = 60
    occupied_heating_min_c: float = 20.0
    occupied_cooling_max_c: float = 26.0
    absolute_min_c: float = 18.0
    absolute_max_c: float = 28.0
    default_heating_setpoint_c: float = 21.0
    default_cooling_setpoint_c: float = 24.5

    def resolved(self, path: Path) -> Path:
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


settings = Settings()
