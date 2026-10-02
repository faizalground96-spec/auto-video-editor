"""presets.py — Tahap 8: paket gaya + 3 mode.

Mode:
  auto        : Gemini bebas memilih dari seluruh katalog.
  preset      : Gemini hanya boleh memakai efek dalam `allowed` paket.
                `fixed` mengunci gaya dasar (text_style/grade).
  auto+kunci  : auto, tetapi ID efek tertentu dimatikan (denied).

Aturan plan: kategori `reframe` tidak dibatasi paket (selalu boleh).
ID dalam `allowed` yang tidak aktif/tidak ada diabaikan (paket tetap valid).
Paket hilang -> kembali ke auto + catat di log (jangan crash).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from .utils import resource_path

log = logging.getLogger("auto_video_editor.presets")

PRESET_DIR = resource_path("presets")


def list_presets(preset_dir: Optional[Path] = None) -> list[str]:
    d = Path(preset_dir) if preset_dir else PRESET_DIR
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def load_preset(name: str,
                preset_dir: Optional[Path] = None) -> Optional[dict]:
    """Muat paket gaya. None bila tak ada (pemanggil fallback ke auto)."""
    d = Path(preset_dir) if preset_dir else PRESET_DIR
    p = d / f"{name}.yaml"
    if not p.is_file():
        log.warning("paket gaya '%s' tak ada -> fallback ke mode auto", name)
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.setdefault("name", name)
    data.setdefault("allowed", [])
    data.setdefault("fixed", {})
    return data


def preset_allowed_ids(preset: dict, registry) -> list[str]:
    """ID efek yang boleh dipakai: allowed ∩ stable, + reframe selalu."""
    allowed_cfg = set(preset.get("allowed") or [])
    ids: list[str] = []
    for eid in registry.all_ids():
        entry = registry.entries[eid]
        if entry.meta.status != "stable":
            continue  # ID tak aktif diabaikan
        if entry.meta.category == "reframe":
            ids.append(eid)  # reframe tak dibatasi paket
        elif eid in allowed_cfg:
            ids.append(eid)
    return ids


def apply_fixed(edl_dict: dict, preset: Optional[dict]) -> dict:
    """Kunci gaya dasar paket (fixed.text_style / fixed.grade)."""
    if not preset:
        return edl_dict
    fixed = preset.get("fixed") or {}
    g = edl_dict.setdefault("global", {})
    if fixed.get("text_style"):
        g["text_style"] = {"id": fixed["text_style"], "params": {}}
    if fixed.get("grade"):
        g["grade"] = {"id": fixed["grade"], "params": {}}
    return edl_dict


def check_preset_compliance(edl_dict: dict, preset: dict,
                            registry) -> list[str]:
    """Kembalikan daftar pelanggaran: efek di luar allowed (selain reframe)."""
    allowed = set(preset_allowed_ids(preset, registry))
    bad: list[str] = []
    for seg in edl_dict.get("segments", []):
        for ef in seg.get("effects", []):
            eid = ef.get("id")
            if eid not in allowed:
                bad.append(f"{eid} di segmen {seg.get('start')}")
    # gaya global juga harus sesuai fixed
    fixed = preset.get("fixed") or {}
    g = edl_dict.get("global", {}) or {}
    ts = (g.get("text_style") or {}).get("id")
    gr = (g.get("grade") or {}).get("id")
    if fixed.get("text_style") and ts != fixed["text_style"]:
        bad.append(f"text_style {ts} != fixed {fixed['text_style']}")
    if fixed.get("grade") and gr != fixed["grade"]:
        bad.append(f"grade {gr} != fixed {fixed['grade']}")
    return bad
