"""Pipeline configuration: config/pipeline.yml, validated on load so a typo fails fast."""
import os
import unicodedata
from datetime import date, timedelta
from functools import cached_property
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get("WX_CONFIG", ROOT / "config" / "pipeline.yml"))


class Source(BaseModel):
    base_url: str
    reference_files: dict[str, str]


class Window(BaseModel):
    last_days: int | None = None
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def one_way(self):
        if (self.last_days is None) == (self.start is None):
            raise ValueError("window: set either last_days or start")
        return self

    def bounds(self, today: date | None = None) -> tuple[date, date]:
        end = self.end or (today or date.today())
        start = self.start or end - timedelta(days=self.last_days)
        return start, end


class City(BaseModel):
    city: str
    province: str
    name_prefix: str | None = None
    station_id: str | None = None

    @property
    def prefix(self) -> str:
        """NOAA station names are upper-case ASCII: Montréal -> MONTREAL."""
        text = self.name_prefix or self.city
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()


class Selection(BaseModel):
    airport_name_pattern: str
    preferred_name_pattern: str
    required_elements: list[str]


class Stations(BaseModel):
    country: str
    selection: Selection
    cities: list[City] = Field(min_length=1)


class Display(BaseModel):
    unit: str
    factor: float


class Elements(BaseModel):
    exclude: list[str] = []
    absent_means_zero: list[str] = []
    bounds: dict[str, tuple[float, float]] = {}
    display: dict[str, Display] = {}


class IntensityRule(BaseModel):
    pattern: str
    element: str
    min: float | None = None
    max: float | None = None


class Narratives(BaseModel):
    provider: str = Field("auto", pattern="^(auto|gemini|mock)$")
    models: list[str] = Field(min_length=1)
    prompt: Path
    days: int = Field(14, ge=1)
    batch_size: int = Field(10, ge=1, le=50)
    requests_per_minute: float = Field(5, gt=0)
    max_requests_per_run: int = Field(30, ge=1)
    temperature: float = 0.3
    repair_attempts: int = Field(1, ge=0, le=1)
    intensity: list[IntensityRule] = []


class Quality(BaseModel):
    freshness_warn_days: int = 7
    freshness_error_days: int = 30
    volume_change_warn_pct: float = 20


class Config(BaseModel):
    source: Source
    window: Window
    stations: Stations
    elements: Elements = Elements()
    narratives: Narratives
    quality: Quality = Quality()

    @cached_property
    def data_dir(self) -> Path:
        return Path(os.environ.get("WX_DATA_DIR", ROOT / "data"))

    @property
    def warehouse(self) -> Path:
        return Path(os.environ.get("WX_WAREHOUSE", self.data_dir / "warehouse.duckdb"))


def load(path: Path = CONFIG_PATH) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
