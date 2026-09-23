from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re
import numpy as np

from .models import CalSetSnapshot, ComplexSeries


def _json_default(value: Any):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, complex):
        return {"real": value.real, "imag": value.imag}
    raise TypeError(f"Not JSON serializable: {type(value)!r}")


def _safe_folder_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    return cleaned or "CalSet"


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")


def _series_index_and_arrays(series_list: list[ComplexSeries], prefix: str):
    index: dict[str, Any] = {}
    arrays: dict[str, np.ndarray] = {}
    for i, series in enumerate(series_list):
        key = f"{prefix}_{i:04d}"
        freq_key = f"{key}_freq_hz"
        data_key = f"{key}_data"
        arrays[freq_key] = np.asarray(series.frequency_hz, dtype=np.float64)
        arrays[data_key] = np.asarray(series.data, dtype=np.complex128)
        index[key] = {
            "name": series.name,
            "raw_name": series.raw_name,
            "frequency_key": freq_key,
            "data_key": data_key,
            "point_count": series.point_count,
            "frequency_point_count": int(series.frequency_hz.size),
            "start_hz": series.start_hz,
            "stop_hz": series.stop_hz,
            "read_errors": series.read_errors,
        }
    return index, arrays


def dump_snapshot(snapshot: CalSetSnapshot, parent_dir: str | Path) -> Path:
    parent = Path(parent_dir)
    parent.mkdir(parents=True, exist_ok=True)
    cal_dir = parent / _safe_folder_name(snapshot.name)
    cal_dir.mkdir(parents=True, exist_ok=True)

    _write_json(cal_dir / "calset_info.json", {
        "schema_version": 1,
        "dumped_at_utc": datetime.now(timezone.utc).isoformat(),
        "name": snapshot.name,
        "info": snapshot.info,
        "properties": snapshot.properties,
        "items": snapshot.items,
    })
    _write_json(cal_dir / "raw_scpi.json", [asdict(record) for record in snapshot.audit])

    std_dir = cal_dir / "standards"
    std_dir.mkdir(exist_ok=True)
    std_index, std_arrays = _series_index_and_arrays(snapshot.standards, "std")
    _write_json(std_dir / "index.json", std_index)
    np.savez_compressed(std_dir / "standards.npz", **std_arrays)

    et_dir = cal_dir / "error_terms"
    et_dir.mkdir(exist_ok=True)
    et_index, et_arrays = _series_index_and_arrays(snapshot.error_terms, "et")
    _write_json(et_dir / "index.json", et_index)
    np.savez_compressed(et_dir / "error_terms.npz", **et_arrays)
    return cal_dir


def write_manifest(target_dir: str | Path, instrument_idn: str | None, visa_resource: str, calsets: list[dict[str, Any]]) -> Path:
    path = Path(target_dir) / "dump_manifest.json"
    _write_json(path, {
        "schema_version": 1,
        "dumped_at_utc": datetime.now(timezone.utc).isoformat(),
        "instrument_idn": instrument_idn,
        "visa_resource": visa_resource,
        "calsets": calsets,
    })
    return path
