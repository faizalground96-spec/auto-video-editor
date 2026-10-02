"""validate.py — Tahap 6: validasi EDL dari Gemini (WAJIB per plan 6e).

Mengembalikan (ok, errors, edl_dict). Bila dry_run=False, hasil akhir
disimpan: edl.json, edl_validation.json, edl_why.txt di work_dir.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from .schema import Edl

log = logging.getLogger("auto_video_editor.validate")

INTENSITIES = ("calm", "medium", "aggressive")
REFRAME_MODES = ("none", "smart_crop", "blur_fill", "fit_letterbox")
REFRAME_FALLBACK_ORDER = ("smart_crop", "blur_fill", "fit_letterbox", "none")


# ---------------------------------------------------------------------------
# Snapping waktu
# ---------------------------------------------------------------------------
def _snap(t: float, words: list[dict], silences: list[dict]) -> float:
    """Rapatkan t ke batas kata terdekat (<=0,3 dtk) atau tengah jeda."""
    best, best_d = t, 0.3
    for w in words:
        for b in (w["start"], w["end"]):
            d = abs(b - t)
            if d <= best_d:
                best, best_d = b, d
    for s in silences:
        mid = (s.get("start", 0) + s.get("end", 0)) / 2
        d = abs(mid - t)
        if d <= best_d:
            best, best_d = mid, d
    return round(best, 3)


# ---------------------------------------------------------------------------
# Parameter
# ---------------------------------------------------------------------------
def _coerce_param(spec, value, fixed: list[str], eid: str,
                  pname: str) -> tuple[bool, Any]:
    """Kembalikan (ok, nilai). Tipe salah -> coba perbaiki, else buang."""
    t = spec.type
    try:
        if t == "float":
            v = float(value)
        elif t == "int":
            v = int(float(value))
        elif t == "bool":
            v = bool(value) if isinstance(value, bool) else \
                str(value).lower() in ("1", "true", "ya")
        elif t == "choice":
            v = str(value)
            if spec.choices and v not in spec.choices:
                return False, None
        elif t == "list":
            v = list(value) if isinstance(value, (list, tuple)) else [value]
        else:  # str
            v = str(value)
    except (ValueError, TypeError):
        fixed.append(f"{eid}.{pname}: tipe salah, dibuang")
        return False, None
    if t in ("float", "int") and spec.min is not None and spec.max is not None:
        lo, hi = spec.min, spec.max
        if v < lo or v > hi:
            clamped = min(max(v, lo), hi)
            fixed.append(f"{eid}.{pname}: {v} di luar [{lo},{hi}] -> {clamped}")
            v = clamped
    return True, v


def _clean_params(eid: str, params: dict, meta, fixed: list[str]) -> dict:
    out = {}
    for k, v in (params or {}).items():
        spec = meta.params.get(k)
        if spec is None:
            fixed.append(f"{eid}: param tak dikenal '{k}' dibuang")
            continue
        ok, nv = _coerce_param(spec, v, fixed, eid, k)
        if ok:
            out[k] = nv
    # isi default yang hilang
    for k, spec in meta.params.items():
        if k not in out and spec.default is not None:
            out[k] = spec.default
    return out


# ---------------------------------------------------------------------------
# Validasi utama
# ---------------------------------------------------------------------------
def validate_edl(raw: dict, registry, words: list[dict],
                 silences: list[dict], duration: float, aspect: str,
                 cfg: dict, dry_run: bool = False,
                 work_dir: Optional[Path] = None,
                 face_detected: bool = False,
                 ) -> tuple[bool, list[str], dict]:
    """Validasi EDL mentah -> (ok, errors, edl_bersih).

    ok=False berarti ada galat fatal (bukan sekadar perbaikan); panggil
    ulang Gemini atau pakai rencana cadangan.
    """
    errors: list[str] = []
    fixed: list[str] = []
    dropped: list[str] = []

    def drop(msg: str):
        dropped.append(msg)
        log.info("validate: %s", msg)

    def fix(msg: str):
        fixed.append(msg)

    # -- skema dasar -------------------------------------------------------
    try:
        edl = Edl.model_validate(raw)
    except Exception as e:
        return False, [f"skema EDL tak valid: {e}"], {}

    d = edl.model_dump(mode="json", by_alias=True)

    # -- intensitas ---------------------------------------------------------
    intensity = d["global"].get("intensity", "medium")
    if intensity not in INTENSITIES:
        fix(f"intensity '{intensity}' -> 'medium'")
        intensity = "medium"
        d["global"]["intensity"] = intensity
    density_cfg = (cfg.get("density", {}) or {}).get(intensity, {})
    max_strong = int(density_cfg.get("max_strong_per_10s", 3))
    min_gap = float(density_cfg.get("min_gap_s", 1.5))

    # -- kanvas & reframe ---------------------------------------------------
    from .canvas import CANVAS_SPECS
    if d["canvas"]["aspect"] not in CANVAS_SPECS:
        return False, [f"aspect tak dikenal: {d['canvas']['aspect']}"], {}
    if d["canvas"]["aspect"] == "auto":
        d["canvas"]["aspect"] = aspect
        fix(f"aspect auto -> {aspect}")
    aspect = d["canvas"]["aspect"]
    rmode = d["canvas"]["reframe"]["mode"]
    if rmode not in REFRAME_MODES:
        # aturan cadangan plan: pilih yang masuk akal
        rmode = "none" if face_detected else "blur_fill"
        fix(f"reframe.mode tak valid -> '{rmode}' (aturan cadangan)")
        d["canvas"]["reframe"]["mode"] = rmode
        d["canvas"]["reframe"]["why"] = (
            d["canvas"]["reframe"].get("why", "")
            + " [koreksi validator: mode tak valid]")

    # -- helper efek ---------------------------------------------------------
    def effect_ok(eid: str) -> tuple[bool, Any]:
        if eid not in registry.entries:
            return False, None
        m = registry.entries[eid].meta
        if m.status != "stable":
            return False, f"status={m.status}"
        if aspect not in m.aspects:
            return False, f"tak mendukung {aspect}"
        return True, m

    # -- global: text_style & grade ------------------------------------------
    for gkey in ("text_style", "grade"):
        g = d["global"].get(gkey)
        if not g:
            continue
        ok, m_or_why = effect_ok(g["id"])
        if not ok:
            drop(f"global.{gkey} {g['id']} dibuang ({m_or_why})")
            d["global"][gkey] = None
            continue
        g["params"] = _clean_params(g["id"], g.get("params"), m_or_why, fixed)

    # -- segmen ---------------------------------------------------------------
    words_by_i = {w["i"]: w for w in words}
    segs = []
    for si, seg in enumerate(d["segments"]):
        s, e = float(seg["start"]), float(seg["end"])
        if e <= s:
            drop(f"segmen {si}: end<=start, dibuang")
            continue
        if s < 0 or e > duration + 0.5:
            if s >= duration:
                drop(f"segmen {si}: di luar durasi, dibuang")
                continue
            s = max(0.0, s)
            e = min(float(duration), e)
            fix(f"segmen {si}: dijepit ke durasi")
        s, e = _snap(s, words, silences), _snap(e, words, silences)
        if e <= s:
            e = round(s + 0.5, 3)
            fix(f"segmen {si}: end diset {e} setelah snapping")
        effs = []
        for ef in seg["effects"]:
            eid = ef["id"]
            ok, m_or_why = effect_ok(eid)
            if not ok:
                drop(f"efek {eid} dibuang ({m_or_why})")
                continue
            at = ef.get("at")
            if at is None and m_or_why.requires_at:
                drop(f"{eid}: butuh 'at', dibuang")
                continue
            if at is not None:
                at = float(at)
                if at < s - 0.5 or at > e + 0.5:
                    drop(f"{eid}: at={at} di luar segmen [{s},{e}]")
                    continue
                at = _snap(max(s, min(e, at)), words, silences)
            effs.append({"id": eid, "at": at,
                         "params": _clean_params(eid, ef.get("params"),
                                                 m_or_why, fixed)})
        # kategori sama tak boleh bertumpuk dalam satu segmen
        seen_cat: dict[str, str] = {}
        kept = []
        for ef in effs:
            cat = registry.entries[ef["id"]].meta.category
            if cat in seen_cat and cat not in ("overlay",):
                drop(f"{ef['id']}: kategori {cat} sudah ada "
                     f"({seen_cat[cat]}), dibuang")
                continue
            seen_cat[cat] = ef["id"]
            kept.append(ef)
        segs.append({"start": s, "end": e, "role": seg.get("role", "body"),
                     "effects": kept, "why": seg.get("why", "")})

    # segmen tak boleh tumpang tindih -> potong yang dulu
    segs.sort(key=lambda x: x["start"])
    for i in range(1, len(segs)):
        if segs[i]["start"] < segs[i - 1]["end"]:
            fix(f"segmen {i}: start {segs[i]['start']} -> "
                f"{segs[i - 1]['end']} (anti tumpang tindih)")
            segs[i]["start"] = segs[i - 1]["end"]
    d["segments"] = segs
    if not segs:
        return False, errors + ["tidak ada segmen valid tersisa"], d

    # -- anggaran efek kuat + min_gap ------------------------------------------
    strong_times: list[tuple[float, str]] = []  # (t, eid)
    for seg in segs:
        for ef in seg["effects"]:
            m = registry.entries[ef["id"]].meta
            if m.strong:
                t = ef["at"] if ef["at"] is not None else seg["start"]
                strong_times.append((t, ef["id"], seg))
    # prioritaskan hook & kata penekanan: urutkan (hook dulu)
    def _prio(item):
        t, eid, seg = item
        return (0 if seg["role"] == "hook" else 1, t)
    strong_times.sort(key=_prio)
    kept_strong: list[tuple[float, str]] = []
    for t, eid, seg in strong_times:
        win_start = (t // 10) * 10
        in_win = sum(1 for kt, _ in kept_strong
                     if win_start <= kt < win_start + 10)
        too_close = any(abs(kt - t) < min_gap for kt, _ in kept_strong)
        if in_win >= max_strong or too_close:
            drop(f"{eid} @ {t:.1f}s: melebihi anggaran "
                 f"({max_strong}/10s, gap {min_gap}s)")
            seg["effects"] = [x for x in seg["effects"] if x["id"] != eid]
        else:
            kept_strong.append((t, eid))

    # -- conflicts_with ----------------------------------------------------------
    for seg in segs:
        ids = [e["id"] for e in seg["effects"]]
        for ef in list(seg["effects"]):
            m = registry.entries[ef["id"]].meta
            clash = [c for c in (m.conflicts_with or []) if c in ids]
            if clash:
                drop(f"{ef['id']}: bentrok dengan {clash}, dibuang")
                seg["effects"].remove(ef)
                ids.remove(ef["id"])

    # -- aturan hook ---------------------------------------------------------------
    if intensity != "calm":
        hook_strong = any(
            seg["start"] < 3.0 and any(
                registry.entries[e["id"]].meta.strong
                for e in seg["effects"])
            for seg in segs if seg["start"] < 3.0)
        # elemen penarik: efek kuat ATAU teks ATAU transisi dalam 3 dtk pertama
        hook_any = any(
            seg["start"] < 3.0 and seg["effects"]
            for seg in segs)
        if not (hook_strong or hook_any):
            errors.append("aturan hook: tak ada elemen penarik dalam 3 dtk")

    # -- emphasis_words ---------------------------------------------------------------
    em = []
    for ew in d.get("emphasis_words", []):
        idx, word = ew["idx"], (ew.get("word") or "").strip()
        w = words_by_i.get(idx)
        if w is None:
            drop(f"emphasis idx={idx}: tak ada di transkrip")
            continue
        if word and word.lower() != w["word"].strip().lower().strip("*"):
            drop(f"emphasis idx={idx}: '{word}' != '{w['word']}' di transkrip")
            continue
        em.append({"idx": idx, "word": w["word"],
                   "start": w["start"], "end": w["end"]})
    d["emphasis_words"] = em

    # -- closing -----------------------------------------------------------------------
    cl = d.get("closing")
    if cl:
        text = (cl.get("text") or "").strip()
        if len(text) > 40:
            text = text[:40]
            fix("closing.text dipotong 40 karakter")
        if re.search(r"https?://|www\.", text):
            drop("closing.text memuat URL, dibuang")
            d["closing"] = None
        else:
            cl["text"] = text

    if errors:
        return False, errors, d

    # -- simpan --------------------------------------------------------------------------
    if not dry_run and work_dir is not None:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "edl.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        (work_dir / "edl_validation.json").write_text(
            json.dumps({"fixed": fixed, "dropped": dropped},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        why_lines = [f"# {d['global'].get('intensity')}"]
        if d["global"].get("why"):
            why_lines.append(f"global: {d['global']['why']}")
        for seg in segs:
            if seg.get("why"):
                why_lines.append(
                    f"[{seg['start']:.1f}-{seg['end']:.1f}] {seg['why']}")
        (work_dir / "edl_why.txt").write_text("\n".join(why_lines) + "\n",
                                              encoding="utf-8")
    d["_validation"] = {"fixed": fixed, "dropped": dropped}
    return True, [], d
