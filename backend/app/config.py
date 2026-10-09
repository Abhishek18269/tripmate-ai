from functools import lru_cache
from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore")

    # Public OSM-based lookup is the normal mode. Demo mode remains available for
    # offline presentations and makes every fallback visibly unverified.
    demo_mode: bool = Field(default=False, validation_alias=AliasChoices("TRIPMATE_DEMO_MODE", "DEMO_MODE"))
    database_url: str = Field(default="sqlite:///./tripmate.db", validation_alias=AliasChoices("TRIPMATE_DATABASE_URL", "DATABASE_URL"))
    cors_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173", validation_alias=AliasChoices("TRIPMATE_CORS_ORIGINS", "CORS_ORIGINS"))
    gemini_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "TRIPMATE_GEMINI_API_KEY"))
    gemma_model: str = Field(default="gemma-4-26b-a4b-it", validation_alias=AliasChoices("GEMMA_MODEL", "TRIPMATE_GEMMA_MODEL"))
    nominatim_base_url: str = Field(default="https://nominatim.openstreetmap.org", validation_alias=AliasChoices("NOMINATIM_BASE_URL", "TRIPMATE_NOMINATIM_BASE_URL"))
    overpass_url: str = Field(default="https://overpass-api.de/api/interpreter", validation_alias=AliasChoices("OVERPASS_URL", "TRIPMATE_OVERPASS_URL"))
    osrm_url: str = Field(default="https://router.project-osrm.org", validation_alias=AliasChoices("OSRM_URL", "TRIPMATE_OSRM_URL"))
    open_meteo_url: str = Field(default="https://api.open-meteo.com/v1/forecast", validation_alias=AliasChoices("OPEN_METEO_URL", "TRIPMATE_OPEN_METEO_URL"))

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

