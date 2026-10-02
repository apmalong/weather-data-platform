"""Reset what the pipeline has built, so the next `wx run` starts over.

    wx reset                 the warehouse (raw, marts, narratives, ops history); keeps downloads
    wx reset --all           also the downloaded NOAA files and the report: like a fresh clone
    wx reset --narratives    only the narrative cache, e.g. to regenerate with a new prompt or model

Only files the pipeline creates are removed, never the whole data folder (WX_DATA_DIR can point
anywhere). Asks for confirmation unless --yes.
"""
import shutil
from pathlib import Path

import duckdb

from wx.config import Config


class ResetRefused(RuntimeError):
    pass


def targets(cfg: Config, everything: bool) -> list[Path]:
    """What a reset removes, existing files only."""
    warehouse = cfg.warehouse
    paths = [warehouse, warehouse.with_name(warehouse.name + ".wal")]
    if everything:
        paths += [cfg.data_dir / "raw", cfg.data_dir / "report.html", cfg.data_dir / "health_report.md"]
    return [p for p in paths if p.exists()]


def describe(cfg: Config, everything: bool, narratives: bool) -> str:
    if narratives:
        return f"the narrative cache (schema `narratives`) in {cfg.warehouse}"
    found = targets(cfg, everything)
    return "\n".join(f"  {p}" for p in found) if found else ""


def reset(cfg: Config, everything: bool = False, narratives: bool = False) -> list[str]:
    if narratives:
        if not cfg.warehouse.exists():
            return []
        conn = duckdb.connect(str(cfg.warehouse))
        try:
            conn.execute("drop schema if exists narratives cascade")
        finally:
            conn.close()
        return ["narratives schema"]
    removed = []
    for path in targets(cfg, everything):
        try:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        except PermissionError as exc:
            raise ResetRefused(f"{path} is in use (is Airflow or a SQL client holding the warehouse?): {exc}") from exc
        removed.append(str(path))
    return removed
