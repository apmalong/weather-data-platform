from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from wx import config
from wx.config import City, Window


def test_repository_config_is_valid():
    cfg = config.load()
    assert [c.city for c in cfg.stations.cities] == ["Toronto", "Montreal", "Vancouver", "Calgary", "Ottawa"]


def test_unquoted_ontario_is_rejected_not_read_as_true():
    raw = yaml.safe_load("{city: Toronto, province: ON}")
    assert raw["province"] is True  # YAML 1.1's "Norway problem"
    with pytest.raises(ValidationError):
        City.model_validate(raw)


def test_city_prefix_matches_noaa_names():
    assert City(city="Montréal", province="QC").prefix == "MONTREAL"
    assert City(city="Toronto", province="ON", name_prefix="Toronto Intl").prefix == "TORONTO INTL"


def test_window_bounds():
    assert Window(last_days=730).bounds(date(2026, 10, 2)) == (date(2024, 10, 2), date(2026, 10, 2))
    assert Window(start=date(2025, 1, 1), end=date(2025, 12, 31)).bounds() == (date(2025, 1, 1), date(2025, 12, 31))
    with pytest.raises(ValidationError):
        Window()
