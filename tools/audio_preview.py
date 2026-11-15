#!/usr/bin/env python3
"""Build a listenable A/B demo of the game's audio.

The first stretch of the file is the *old* runtime sound: the five tones that
scripts/sfx.gd used to synthesise live in-game. The rest is the current palette
played through the same event order, with the battle music and the voice barks
mixed in at the levels the game actually uses. Useful for judging the mix
without launching the engine.

`--board` writes a second file instead: every shipped sound, one at a time,
each announced by name. That one is for pointing at a specific sound - "the
third hit is dull" is easy to say after hearing it labelled, and hopeless to
describe from memory. Both are written to docs/ as .wav and, when afconvert
exists, .m4a.

    python3 tools/audio_preview.py            # -> docs/audio_ab.wav
    python3 tools/audio_preview.py --board    # -> docs/audio_board.wav
"""

from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

import dsp
from dsp import SR

ROOT = Path(__file__).resolve().parent.parent
SFX = ROOT / "assets" / "audio" / "sfx"
VOICE = ROOT / "assets" / "audio" / "voice"
MUSIC = ROOT / "assets" / "audio" / "music"
OUT = ROOT / "docs" / "audio_ab.wav"
BOARD = ROOT / "docs" / "audio_board.wav"
LABEL_CACHE = ROOT / "tools" / "cache" / "labels"

# Trims that mirror the EVENTS table in scripts/sfx.gd.
GAIN = {
    "hit_light": 0.0, "hit_medium": 0.0, "hit_heavy": 0.0, "launcher": 0.0,
    "whoosh_light": -3.0, "whoosh_heavy": -2.0, "block": -1.0, "dash": -2.0,
    "poof": -4.0, "chakra_charge": -4.0, "chakra_shoot": 0.0, "chakra_hit": 0.0,
    "jump": -3.0, "land": -2.0, "ko": 0.0, "round_start": 0.0, "time_up": 0.0,
    "ui_move": 0.0, "ui_confirm": 0.0, "aura_loop": -14.0,
}
MASTER_DB = -3.0
MUSIC_DB = -11.0 + MASTER_DB
VOICE_DB = -3.0 + MASTER_DB


def db(x: np.ndarray, gain_db: float) -> np.ndarray:
    return x * (10.0 ** (gain_db / 20.0))


def load(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as f:
        data = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
    return data


def old_tone(f0: float, f1: float, dur: float, shape: str, vol: float, rate: int = 22050) -> np.ndarray:
    """Byte-for-byte the naive tone the runtime used to generate on the fly."""
    n = int(dur * rate)
    t = np.arange(n) / rate
    freq = f0 + (f1 - f0) * (t / dur)
    phase = np.cumsum(freq) / rate
    w = phase - np.floor(phase)
    if shape == "square":
        s = np.where(w < 0.5, 1.0, -1.0)
    elif shape == "saw":
        s = w * 2.0 - 1.0
    else:
        s = np.sin(2.0 * np.pi * w)
    env = np.minimum(1.0, t * 60.0) * np.maximum(0.0, 1.0 - t / dur)
    out = np.clip(s * env * vol, -1.0, 1.0)
    return dsp.resample(out, SR / rate)


def render_old() -> np.ndarray:
    """The same beats the game used to play, in the old five-tone palette."""
    dur = 3.9
    out = np.zeros(int(dur * SR))
    events = [
        (0.10, old_tone(220.0, 90.0, 0.07, "square", 0.5), -6.0),
        (0.45, old_tone(900.0, 160.0, 0.10, "saw", 0.75), -4.0),
        (0.90, old_tone(150.0, 60.0, 0.09, "square", 0.5), -7.0),
        (1.30, old_tone(520.0, 210.0, 0.13, "saw", 0.4), -8.0),
        (1.90, old_tone(500.0, 55.0, 0.65, "saw", 0.7), -3.0),
    ]
    for at, clip, gain in events:
        dsp.place(out, db(clip, gain), at)
    return out


def render_new() -> np.ndarray:
    """A short scripted exchange using the real assets and the real mix."""
    dur = 13.6
    out = np.zeros(int(dur * SR))

    def sfx(name: str, at: float, extra_db: float = 0.0) -> None:
        dsp.place(out, db(load(SFX / f"{name}.wav"), GAIN[name] + MASTER_DB + extra_db), at)

    def voice(line: str, at: float, pitch: float = 1.0) -> None:
        clip = dsp.pitch_shift(load(VOICE / f"{line}.wav"), 12.0 * np.log2(pitch)) if pitch != 1.0 else load(VOICE / f"{line}.wav")
        dsp.place(out, db(clip, VOICE_DB), at)

    # Music bed, exactly as the runtime plays it (looped, ducked under the KO).
    bed = load(MUSIC / "battle_loop.wav")
    loops = int(np.ceil(dur / (len(bed) / SR)))
    music = np.tile(bed, loops)[: len(out)] * (10.0 ** (MUSIC_DB / 20.0))
    # Duck it while the first hits land, the way sfx.duck() does in game.
    duck_lo, duck_hi = int(1.3 * SR), int(3.6 * SR)
    music[duck_lo:duck_hi] *= 10.0 ** (-5.0 / 20.0)
    out += music

    sfx("round_start", 0.05)
    sfx("whoosh_light", 1.35)
    voice("attack_light", 1.35)
    sfx("hit_light", 1.52)
    sfx("whoosh_light", 1.95)
    voice("attack_light", 1.95)
    sfx("hit_medium", 2.12)
    voice("hurt", 2.16)
    sfx("jump", 2.60)
    sfx("whoosh_heavy", 3.05)
    voice("attack_heavy", 3.05)
    sfx("launcher", 3.22)
    sfx("dash", 4.00)
    sfx("poof", 4.25, -4.0)
    sfx("land", 4.55)
    sfx("chakra_charge", 5.10)
    voice("technique", 5.15)
    sfx("chakra_shoot", 5.85)
    sfx("chakra_hit", 6.60)
    voice("hurt", 6.62)
    sfx("whoosh_heavy", 7.60)
    sfx("launcher", 7.77)
    voice("ko", 7.80)
    sfx("ko", 7.90)
    # Result sting, with the music cut as the K.O. lands.
    cut = int(7.9 * SR)
    out[cut:] *= 10.0 ** (-14.0 / 20.0)
    dsp.place(out, db(load(MUSIC / "result_sting.wav"), MUSIC_DB + 3.0), 9.30)
    voice("win", 9.60)
    return out


def write(path: Path, data: np.ndarray) -> None:
    """Write one mono 16-bit wav, fading the edges so nothing clicks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dsp.fade(data, 0.005, 0.02)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(dsp.to_int16(data).tobytes())
    print(f"  {path.relative_to(ROOT)}  {len(data) / SR:.1f}s")
    m4a = path.with_suffix(".m4a")
    try:
        subprocess.run(
            ["afconvert", "-f", "m4af", "-d", "aac", "-b", "128000", str(path), str(m4a)],
            check=True, capture_output=True,
        )
        print(f"  {m4a.relative_to(ROOT)}")
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"  (skipped m4a: {exc})")


# ------------------------------------------------------------ named board

# The order the board walks the palette in: the impact ladder first, then the
# movement and utility sounds, then the big moments, then the barks.
BOARD_ORDER = [
    "hit_light", "hit_medium", "hit_heavy", "launcher",
    "whoosh_light", "whoosh_heavy", "block", "dash", "poof",
    "jump", "land", "chakra_charge", "chakra_shoot", "chakra_hit",
    "aura_loop", "round_start", "ko", "time_up", "ui_move", "ui_confirm",
]


def announce(text: str) -> np.ndarray:
    """A spoken name for a sound, cached so a re-run costs no API calls."""
    slug = "".join(c if c.isalnum() else "_" for c in text.lower())
    path = LABEL_CACHE / f"{slug}.wav"
    if path.exists():
        return load(path)
    import gen_voices  # the TTS client already lives here; import is lazy

    take = gen_voices.trim(gen_voices.decode(
        gen_voices.tts(text, gen_voices.DEFAULT_VOICE, gen_voices.DEFAULT_PROVIDER)))
    # The label is a caption, not part of the mix: keep it clearly under the
    # sound it introduces, or every clip is judged against a loud voice.
    take = dsp.level(take, -19.0, 0.85)
    LABEL_CACHE.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(dsp.to_int16(take).tobytes())
    return take


def render_board() -> np.ndarray:
    """Every shipped sound once, announced by name, at the level the game uses."""
    board: list[np.ndarray] = []
    for name in BOARD_ORDER:
        board += [announce(name.replace("_", " ")), dsp.silence(0.18),
                  db(load(SFX / f"{name}.wav"), GAIN[name] + MASTER_DB), dsp.silence(0.55)]
    board.append(dsp.silence(0.9))
    for line in ["attack_light", "attack_heavy", "technique", "hurt", "ko", "win"]:
        board += [announce("voice " + line.replace("_", " ")), dsp.silence(0.18),
                  db(load(VOICE / f"{line}.wav"), VOICE_DB), dsp.silence(0.5)]
    board.append(dsp.silence(0.6))
    board += [announce("battle music"), dsp.silence(0.3)]
    music = load(MUSIC / "battle_loop.wav")[: int(6.0 * SR)]
    board.append(db(music, MUSIC_DB + MASTER_DB))
    return np.concatenate(board)


def main() -> int:
    if "--board" in sys.argv:
        board = render_board()
        peak = float(np.max(np.abs(board)))
        if peak > 0.97:
            board *= 0.97 / peak
        write(BOARD, board)
        return 0

    gap = np.zeros(int(0.9 * SR))
    parts = [render_old(), gap, render_new()]
    data = np.concatenate(parts)
    # Keep the absolute level sane; the relative mix inside each section is the
    # thing being demonstrated, so only a global peak guard is applied here.
    peak = float(np.max(np.abs(data)))
    if peak > 0.97:
        data *= 0.97 / peak
    write(OUT, data)
    print(f"  old section: 0.0-{len(parts[0]) / SR:.1f}s   ->  new section: "
          f"{(len(parts[0]) + len(gap)) / SR:.1f}s-end")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
