"""text.karaoke_highlight — kata aktif disorot sinkron ucapan.

Satu Dialogue per event caption; tiap kata diberi {\\k<dur>} (durasi
dalam centisecond) sehingga sorotan berjalan mengikuti kata yang
diucapkan. Warna sorot: kuning (atau merah bila highlight_color=red).
"""
from app.schema import EffectContext, EffectOutput
from app.subtitles import (RED, YELLOW, chunk_captions, segment_words)

META = {
    "id": "text.karaoke_highlight",
    "category": "text",
    "status": "stable",
    "version": 1,
    "description": "Sorotan karaoke berjalan per kata, sinkron dengan ucapan.",
    "good_for": ["energetic", "music", "hook"],
    "avoid_for": ["calm", "serious"],
    "params": {
        "highlight_color": {"type": "str", "default": "yellow",
                            "options": ["yellow", "red"]},
    },
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["text.clean_caption", "text.pop_in_word",
                       "text.typewriter", "text.red_keyword"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    words = segment_words(ctx)
    if not words:
        return EffectOutput()
    color = RED if params.get("highlight_color") == "red" else YELLOW
    events = []
    for cap in chunk_captions(words, ctx.canvas, ctx.config):
        cwords = cap["words"]
        if not cwords:
            continue
        line_of = {}
        for li, idxs in enumerate(cap["line_words"]):
            for ii in idxs:
                line_of[ii] = li
        parts = []
        prev_end, prev_line = cap["start"], 0
        for j, w in enumerate(cwords):
            li = line_of.get(w.get("i", j), 0)
            if li > prev_line:
                parts.append("\\N")
                prev_line = li
            gap_cs = int(round((w["start"] - prev_end) * 100))
            if gap_cs > 0:
                parts.append(f"{{\\k{gap_cs}}}")  # jeda: sorot diam
            dur_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
            parts.append(f"{{\\k{dur_cs}}}{w['word'].strip()}")
            prev_end = w["end"]
        # gabung: spasi antar kata, tapi bukan di sekitar \N
        text = ""
        for p in parts:
            if p == "\\N":
                text += p
            else:
                text += (" " if text and not text.endswith("\\N") else "") + p
        events.append({
            "start": cap["start"],
            "end": cap["end"],
            # SecondaryColour = warna sorot karaoke
            "text": f"{{\\2c{color}}}" + text,
            "style": "Caption",
        })
    return EffectOutput(ass_events=events)
