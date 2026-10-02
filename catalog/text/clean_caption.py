"""text.clean_caption — caption sederhana dua baris, kalem, tanpa animasi."""
from app.schema import EffectContext, EffectOutput

META = {
    "id": "text.clean_caption",
    "category": "text",
    "status": "stable",
    "version": 1,
    "description": "Caption sederhana maksimal dua baris, kalem, tanpa animasi. "
                   "Gaya teks default yang aman untuk semua video.",
    "good_for": ["calm", "education", "serious", "vlog"],
    "avoid_for": ["high_energy", "hype"],
    "params": {},
    "aspects": ["9:16", "16:9", "1:1", "4:5"],
    "max_per_10s": 999,   # gaya dasar, bukan efek kuat
    "strong": False,
    "min_gap": 0.0,
    "conflicts_with": ["text.pop_in_word", "text.karaoke_highlight",
                       "text.typewriter"],
    "requires": {"assets": [], "face": False},
    "sfx": None,
}


def _chunk(words: list[dict], max_chars: int) -> list[tuple[str, float, float]]:
    """Kelompokkan kata jadi baris (<= max_chars), lalu 2 baris per event."""
    lines: list[tuple[str, float, float]] = []
    cur: list[dict] = []

    def cur_text() -> str:
        return " ".join(w["word"].strip() for w in cur)

    def flush_line() -> None:
        if cur:
            lines.append((cur_text(), cur[0]["start"], cur[-1]["end"]))
            cur.clear()

    for w in words:
        word = w["word"].strip()
        trial = (cur_text() + " " + word) if cur else word
        if len(trial) <= max_chars or not cur:
            cur.append(w)
        else:
            flush_line()
            cur.append(w)
    flush_line()

    events = []
    for i in range(0, len(lines), 2):
        pair = lines[i:i + 2]
        text = "\\N".join(t for t, _, _ in pair)
        events.append((text, pair[0][1], pair[-1][2]))
    return events


def build(ctx: EffectContext, at, params: dict) -> EffectOutput:
    words = ctx.words or []
    if not words:
        return EffectOutput()
    max_chars = ctx.config["caption"]["max_chars_per_line"][
        ctx.canvas.orientation]
    events = [
        {"start": s, "end": e, "text": t, "style": "Caption"}
        for t, s, e in _chunk(words, max_chars)
    ]
    return EffectOutput(ass_events=events)
