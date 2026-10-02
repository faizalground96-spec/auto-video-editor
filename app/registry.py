"""registry.py — pemuat & validator katalog efek.

Sengaja bernama registry.py (bukan catalog.py) agar tidak bentrok dengan
folder catalog/. Memuat tiap file .py via importlib (bukan impor paket),
sehingga jalan juga di aplikasi PyInstaller hasil build.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .schema import EffectContext, EffectMeta, EffectOutput
from .utils import log


@dataclass
class CatalogEntry:
    meta: EffectMeta
    module: Any
    path: Path


class EffectRegistry:
    def __init__(self, catalog_dir: str | Path,
                 assets_dir: Optional[str | Path] = None):
        self.catalog_dir = Path(catalog_dir)
        self.assets_dir = Path(assets_dir) if assets_dir else None
        self.entries: dict[str, CatalogEntry] = {}
        self.errors: list[tuple[Path, str]] = []  # (file, pesan) yg dilewati

    # -- pemuatan ---------------------------------------------------------
    def load(self) -> "EffectRegistry":
        files = sorted(self.catalog_dir.rglob("*.py"))
        for fp in files:
            if fp.name.startswith("_"):
                continue
            try:
                self._load_one(fp)
            except Exception as e:  # satu file rusak tak boleh menjatuhkan app
                msg = f"{type(e).__name__}: {e}"
                self.errors.append((fp, msg))
                log.warning("efek dilewati %s: %s", fp.name, msg)
        log.info("katalog: %d efek aktif, %d dilewati",
                 len(self.entries), len(self.errors))
        return self

    def _load_one(self, fp: Path) -> None:
        # Muat BERDASARKAN PATH FILE (bukan impor paket) agar jalan di
        # PyInstaller. Sengaja compile dari source yang dibaca fresh:
        # cache .pyc bisa basi bila file diubah cepat (mtime+size sama)
        # sehingga META lama yang terbaca dan fingerprint salah.
        mod_name = f"_catalog_{fp.parent.name}_{fp.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, fp)
        if spec is None:
            raise ImportError("spec tidak bisa dibuat")
        module = importlib.util.module_from_spec(spec)
        source = fp.read_text(encoding="utf-8")
        code = compile(source, str(fp), "exec")
        exec(code, module.__dict__)
        raw_meta = getattr(module, "META", None)
        if raw_meta is None:
            raise ValueError("tidak ada META")
        meta = EffectMeta.model_validate(raw_meta)
        # id harus "<kategori>.<nama>" dan cocok dengan foldernya
        cat, _, _name = meta.id.partition(".")
        if not _name or cat != meta.category:
            raise ValueError(
                f"id '{meta.id}' harus berformat '<kategori>.<nama>'")
        if fp.parent.name != meta.category:
            raise ValueError(
                f"file di folder '{fp.parent.name}' tapi kategori META "
                f"'{meta.category}'")
        if not callable(getattr(module, "build", None)):
            raise ValueError("tidak ada fungsi build(ctx, at, params)")
        if meta.id in self.entries:
            raise ValueError(f"id ganda: {meta.id}")
        self.entries[meta.id] = CatalogEntry(meta, module, fp)

    # -- akses ------------------------------------------------------------
    def get(self, effect_id: str) -> CatalogEntry:
        return self.entries[effect_id]

    def all_ids(self) -> list[str]:
        return sorted(self.entries)

    def _assets_ok(self, meta: EffectMeta) -> bool:
        """requires.assets terpenuhi: tiap kunci = subfolder assets berisi file."""
        if not meta.requires.assets:
            return True
        if self.assets_dir is None:
            return False
        for key in meta.requires.assets:
            d = self.assets_dir / key
            if not d.is_dir() or not any(d.iterdir()):
                return False
        return True

    def offerable(self, effect_id: str, aspect: str,
                  face_detected: bool = False) -> tuple[bool, str]:
        """Layak ditawarkan ke Gemini? -> (ya/tidak, alasan)."""
        e = self.entries[effect_id]
        m = e.meta
        if m.status != "stable":
            return False, f"status={m.status}"
        if aspect not in m.aspects:
            return False, f"tak mendukung {aspect}"
        if not self._assets_ok(m):
            return False, "aset wajib kosong"
        if m.requires.face and not face_detected:
            return False, "butuh wajah"
        return True, "ok"

    def describe(self, aspect: str, allowed: Optional[list[str]] = None,
                 denied: Optional[list[str]] = None,
                 face_detected: bool = False) -> str:
        """Ringkasan ringkas katalog untuk prompt Gemini (~satu baris/efek)."""
        lines = []
        for eid in self.all_ids():
            if allowed is not None and eid not in allowed:
                continue
            if denied is not None and eid in denied:
                continue
            ok, _why = self.offerable(eid, aspect, face_detected)
            if not ok:
                continue
            m = self.entries[eid].meta
            params = ", ".join(
                f"{k} [{p.type}"
                + (f" {p.min}-{p.max}" if p.min is not None else "")
                + f" default={p.default}]"
                for k, p in m.params.items()
            )
            lines.append(
                f"- {m.id}: {m.description} "
                f"(cocok: {', '.join(m.good_for) or '-'}; "
                f"hindari: {', '.join(m.avoid_for) or '-'}; "
                f"param: {params or '-'}; "
                f"kuat={'ya' if m.strong else 'tidak'})"
            )
        return "\n".join(lines)

    def fingerprint(self) -> str:
        """Hash isi katalog — dipakai membatalkan cache EDL bila berubah."""
        h = hashlib.sha256()
        for eid in self.all_ids():
            e = self.entries[eid]
            h.update(eid.encode())
            h.update(str(e.meta.version).encode())
            h.update(json.dumps(e.meta.model_dump(mode="json"),
                                sort_keys=True).encode())
        return h.hexdigest()[:16]

    # -- build efek dengan validasi parameter ------------------------------
    def build(self, effect_id: str, ctx: EffectContext,
              at: Optional[float], params: Optional[dict] = None
              ) -> EffectOutput:
        entry = self.get(effect_id)
        clean = self._clean_params(entry.meta, params or {})
        out = entry.module.build(ctx, at, clean)
        if not isinstance(out, EffectOutput):
            raise TypeError(f"{effect_id}.build() harus kembalikan "
                            f"EffectOutput")
        return out

    @staticmethod
    def _clean_params(meta: EffectMeta, params: dict) -> dict:
        """Buang param tak dikenal; jepit ke min/max; pakai default."""
        clean: dict = {}
        for name, spec in meta.params.items():
            v = params.get(name, spec.default)
            if v is None:
                continue
            try:
                if spec.type == "float":
                    v = float(v)
                    if spec.min is not None:
                        v = max(spec.min, v)
                    if spec.max is not None:
                        v = min(spec.max, v)
                elif spec.type == "int":
                    v = int(v)
                    if spec.min is not None:
                        v = max(int(spec.min), v)
                    if spec.max is not None:
                        v = min(int(spec.max), v)
                elif spec.type == "bool":
                    v = bool(v)
                elif spec.type == "str":
                    v = str(v)
                elif spec.type == "choice":
                    if spec.choices and v not in spec.choices:
                        v = spec.default
                elif spec.type == "list":
                    if not isinstance(v, (list, tuple)):
                        v = spec.default
                    else:
                        v = list(v)
            except (ValueError, TypeError):
                v = spec.default
            clean[name] = v
        unknown = set(params) - set(meta.params)
        if unknown:
            log.debug("%s: param tak dikenal dibuang: %s", meta.id, unknown)
        return clean
