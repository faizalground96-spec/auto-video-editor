"""canvas.py — ukuran kanvas, orientasi, safe area, konversi persen -> piksel.

Semua efek memakai koordinat/ukuran RELATIF (persen lebar/tinggi kanvas),
bukan piksel tetap. Ukuran font = persen tinggi kanvas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Aspect = Literal["9:16", "16:9", "1:1", "4:5"]
Orientation = Literal["vertical", "horizontal", "square"]

# Kanvas baku per rasio output.
CANVAS_SPECS: dict[str, dict] = {
    "9:16": {"width": 1080, "height": 1920, "orientation": "vertical",
             "layout": "vertical"},
    "16:9": {"width": 1920, "height": 1080, "orientation": "horizontal",
             "layout": "horizontal"},
    "1:1": {"width": 1080, "height": 1080, "orientation": "square",
            "layout": "square"},
    # 4:5 = portrait feed; memakai varian layout vertikal.
    "4:5": {"width": 1080, "height": 1350, "orientation": "vertical",
            "layout": "vertical"},
}

# Safe area: (atas, bawah, kiri_kanan) dalam persen.
# Bisa dioverride via config.yaml bila perlu.
SAFE_AREAS: dict[str, tuple[float, float, float]] = {
    "9:16": (0.12, 0.22, 0.06),
    "16:9": (0.05, 0.05, 0.05),
    "1:1": (0.06, 0.06, 0.06),
    "4:5": (0.06, 0.06, 0.06),
}


def resolve_aspect(mode: str, source_ratio: float) -> str:
    """Tentukan rasio output.

    mode='auto' -> rasio terdekat dengan sumber (jarak log-rasio);
    bila seri (jarak sama) -> '16:9'.
    """
    if mode != "auto":
        if mode not in CANVAS_SPECS:
            raise ValueError(f"rasio tidak dikenal: {mode}")
        return mode  # type: ignore[return-value]
    targets = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1.0, "4:5": 4 / 5}
    log_src = math.log(source_ratio)
    best, best_d = "16:9", float("inf")
    for name, r in targets.items():
        d = abs(log_src - math.log(r))
        # seri (selisih < epsilon) -> 16:9 menang sesuai aturan plan
        if d < best_d - 1e-9:
            best, best_d = name, d
    return best


@dataclass
class Canvas:
    """Kanvas render target."""
    width: int
    height: int
    aspect: str
    orientation: Orientation
    layout: str                      # vertical | horizontal | square
    safe_top: float = 0.05           # persen tinggi
    safe_bottom: float = 0.05
    safe_side: float = 0.05          # persen lebar

    @classmethod
    def from_aspect(cls, aspect: str,
                    safe_override: tuple[float, float, float] | None = None,
                    ) -> "Canvas":
        spec = CANVAS_SPECS[aspect]
        safe = safe_override or SAFE_AREAS[aspect]
        return cls(width=spec["width"], height=spec["height"],
                   aspect=aspect, orientation=spec["orientation"],
                   layout=spec["layout"],
                   safe_top=safe[0], safe_bottom=safe[1], safe_side=safe[2])

    # -- helper persen -> piksel -------------------------------------------
    def w(self, pct: float) -> int:
        """Persentase lebar kanvas -> piksel."""
        return int(round(self.width * pct))

    def h(self, pct: float) -> int:
        """Persentase tinggi kanvas -> piksel."""
        return int(round(self.height * pct))

    def font_px(self, pct: float) -> int:
        """Ukuran font: persen TINGGI kanvas -> piksel."""
        return int(round(self.height * pct))

    def safe_rect(self) -> tuple[int, int, int, int]:
        """Kotak aman (x, y, w, h) dalam piksel."""
        x = self.w(self.safe_side)
        y = self.h(self.safe_top)
        w = self.width - 2 * x
        h = self.height - self.h(self.safe_top) - self.h(self.safe_bottom)
        return (x, y, w, h)

    def point(self, x_pct: float, y_pct: float) -> tuple[int, int]:
        """Titik relatif (0..1, 0..1) -> piksel."""
        return (self.w(x_pct), self.h(y_pct))
