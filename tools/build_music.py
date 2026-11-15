#!/usr/bin/env python3
"""Render the game's background music from scratch.

Two pieces, both synthesised with tools/dsp.py so nothing is sampled or
licensed:

  * battle_loop.wav  - a seamless 16-bar taiko + koto + shakuhachi groove in A
    minor, the "two ninja staring each other down on a rooftop" cue.
  * result_sting.wav - the KO / victory sting.

The loop is rendered tail-wrapped (see dsp.place_wrap): a ringing hit that runs
past the last beat lands back on the first beat, so the loop point is silent -
literally, there is no fade and no gap, the waveform simply continues.

    python3 tools/build_music.py            # render into assets/audio/music
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import dsp
import godot_reimport
from build_audio import body, crack, master, metal_hit, thud, write
from dsp import SR

ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "assets" / "audio" / "music"

BPM = 138.0
BEAT = 60.0 / BPM
BAR = BEAT * 4.0
BARS = 16
LOOP_SAMPLES = int(round(BARS * BAR * SR))

# Note table (A minor, with the raised 7th used as the dominant colour).
NOTE = {
    "E2": 82.41, "F2": 87.31, "G2": 98.00, "A2": 110.00, "B2": 123.47,
    "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.00, "A3": 220.00, "B3": 246.94,
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.00, "A4": 440.00,
    "C5": 523.25, "D5": 587.33, "E5": 659.25, "G5": 783.99, "A5": 880.00,
    "G#3": 207.65, "G#4": 415.30,
}


# ------------------------------------------------------------- instruments

def taiko(freq: float = 110.0, dur: float = 0.62, seed: int = 101) -> np.ndarray:
    """Big drum: swept thud, skin crack, and a low sub that carries the beat."""
    return dsp.reverb(dsp.saturate(dsp.mix(
        thud(dur, freq, freq * 0.34, 10.0, curve=1.4) * 1.15,
        crack(0.26, 1250.0, 20.0, 1.0, seed=seed) * 0.38,
        dsp.sine(freq * 0.55, dur * 0.85) * dsp.env_ad(dur * 0.85, 0.002, 11.0) * 0.65,
    ), 1.45), room=0.3, decay=0.45)


def shime(seed: int = 211) -> np.ndarray:
    """Tight rim shot for the off-beat groove."""
    dur = 0.13
    return dsp.mix(
        dsp.bandpass(dsp.noise(dur, seed), 2400.0, 1.1) * dsp.env_ad(dur, 0.0008, 60.0),
        dsp.sine(1450.0, dur) * dsp.env_ad(dur, 0.001, 70.0) * 0.35,
        body(dur, 420.0, 45.0, seed=seed + 1) * 0.4,
    )


def shaker(dur: float = 0.07, seed: int = 311) -> np.ndarray:
    return dsp.bandpass(dsp.noise(dur, seed), 6800.0, 0.8) * dsp.env_ad(dur, 0.004, 26.0)


def koto(freq: float, dur: float, seed: int = 401) -> np.ndarray:
    """Plucked string, slightly darker than a raw karplus so it sits in a mix."""
    pluck = dsp.karplus(freq, dur, damp=0.4995, seed=seed)
    pluck = dsp.onepole_lp(pluck, 5200.0)
    return dsp.reverb(pluck * dsp.env_ad(dur, 0.001, 4.2), room=0.24, decay=0.35)


def shakuhachi(freq: float, dur: float, seed: int = 501, vib: float = 5.2) -> np.ndarray:
    """Breathy flute: a few harmonics plus band-passed breath noise."""
    t = dsp.t_axis(dur)
    wobble = 1.0 + 0.0055 * np.sin(2.0 * np.pi * vib * t + 0.6)
    phase = np.cumsum(2.0 * np.pi * freq * wobble / SR)
    tone = np.sin(phase) + 0.32 * np.sin(2.0 * phase) + 0.10 * np.sin(3.0 * phase)
    breath = dsp.bandpass(dsp.noise(dur, seed), 2300.0, 0.7) * 0.20
    env = dsp.env_adsr(dur, 0.055, 0.09, 0.86, min(0.2, dur * 0.35))
    return dsp.reverb((tone * 0.55 + breath) * env, room=0.3, decay=0.4)


def bass_note(freq: float, dur: float) -> np.ndarray:
    x = dsp.sine(freq, dur) * 0.62 + dsp.sine(freq * 2.0, dur) * 0.26 + dsp.sine(freq * 3.0, dur) * 0.10
    return dsp.onepole_lp(x, 620.0) * dsp.env_ad(dur, 0.006, 5.0)


def crash(seed: int = 601) -> np.ndarray:
    """Ringing metal accent, used to glue the loop point together."""
    dur = 1.5
    return dsp.reverb(metal_hit(dur, [
        (1480.0, 0.55, 0.7), (2130.0, 0.42, 0.5), (2970.0, 0.3, 0.35),
        (4210.0, 0.2, 0.25), (5900.0, 0.12, 0.16),
    ], seed=seed) * 0.5, room=0.4, decay=0.6)


# ------------------------------------------------------------------ score

# One chord per bar. Am / F / G / E is the classic minor-key anime cadence, and
# the E with a G# is what makes it read as "Japanese" rather than generic pop.
KOTO_PATTERNS = {
    "Am": ["A3", "C4", "E4", "A4", "E4", "C4", "D4", "E4"],
    "F":  ["C4", "F4", "A4", "C5", "A4", "F4", "G4", "A4"],
    "G":  ["G3", "B3", "D4", "G4", "D4", "B3", "C4", "D4"],
    "E":  ["E3", "G#3", "B3", "E4", "B3", "G#3", "A3", "B3"],
}

PROGRESSION = ["Am", "Am", "Am", "Am", "F", "G", "Am", "E",
               "Am", "Am", "F", "G", "Am", "F", "E", "E"]

BASS_ROOT = {"Am": "A2", "F": "F2", "G": "G2", "E": "E2"}

# (bar, beat, note, length in beats)
MELODY_A = [
    (5, 0.0, "A4", 1.0), (5, 1.0, "C5", 0.5), (5, 1.5, "D5", 1.5), (5, 3.0, "E5", 1.0),
    (6, 0.0, "D5", 1.5), (6, 1.5, "C5", 0.5), (6, 2.0, "A4", 2.0),
    (7, 0.0, "C5", 1.0), (7, 1.0, "D5", 0.5), (7, 1.5, "E5", 0.5), (7, 2.0, "G5", 2.0),
    (8, 0.0, "E5", 1.5), (8, 1.5, "D5", 0.5), (8, 2.0, "C5", 1.0), (8, 3.0, "D5", 1.0),
]

MELODY_B = [
    (11, 0.0, "A5", 1.0), (11, 1.0, "G5", 0.5), (11, 1.5, "E5", 1.5), (11, 3.0, "D5", 1.0),
    (12, 0.0, "E5", 1.0), (12, 1.0, "A5", 1.0), (12, 2.0, "G5", 2.0),
    (13, 0.0, "E5", 0.5), (13, 0.5, "G5", 0.5), (13, 1.0, "A5", 1.5), (13, 2.5, "G5", 1.5),
    (14, 0.0, "E5", 2.0), (14, 2.0, "D5", 1.0), (14, 3.0, "E5", 1.0),
]


def _at(bar: int, beat: float) -> float:
    return (bar - 1) * BAR + beat * BEAT


def render_battle_loop() -> np.ndarray:
    out = np.zeros(LOOP_SAMPLES)

    # --- taiko + shime groove -------------------------------------------
    for bar in range(1, BARS + 1):
        if bar <= 2:
            # Two-bar drum intro: sparse, then a roll that sets up the groove.
            for beat in (0.0, 2.0):
                dsp.place_wrap(out, taiko(110.0, 0.7, seed=100 + bar) * (1.0 if beat == 0.0 else 0.85), _at(bar, beat))
            if bar == 2:
                for step in range(8):
                    dsp.place_wrap(out, shime(seed=230 + step) * (0.5 + 0.045 * step), _at(bar, 2.0 + step * 0.25))
            continue

        dsp.place_wrap(out, taiko(110.0, 0.66, seed=100 + bar), _at(bar, 0.0))
        dsp.place_wrap(out, taiko(98.0, 0.6, seed=140 + bar) * 0.8, _at(bar, 2.0))
        for beat, gain in ((1.5, 0.5), (2.5, 0.45), (3.5, 0.55)):
            dsp.place_wrap(out, shime(seed=210 + int(beat * 4) + bar) * gain, _at(bar, beat))
        if bar in (15, 16):
            # Turnaround fill: eight rim shots across beat 3, wrapping into the loop.
            for step in range(4):
                dsp.place_wrap(out, shime(seed=260 + step + bar * 3) * (0.6 + 0.09 * step), _at(bar, 3.0 + step * 0.25))
            dsp.place_wrap(out, taiko(124.0, 0.5, seed=300 + bar) * 0.9, _at(bar, 3.75))

    # --- shaker bed ------------------------------------------------------
    for bar in range(3, BARS + 1):
        for step in range(8):
            beat = step * 0.5
            accent = 0.85 if step % 2 else 0.5
            dsp.place_wrap(out, shaker(seed=310 + step + bar) * accent, _at(bar, beat))

    # --- koto ostinato ---------------------------------------------------
    for bar in range(3, BARS + 1):
        pattern = KOTO_PATTERNS[PROGRESSION[bar - 1]]
        for step, name in enumerate(pattern):
            gain = 0.9 if step in (0, 4) else 0.62
            if bar in (13, 14, 15):
                gain *= 1.06
            dsp.place_wrap(out, koto(NOTE[name], 0.5, seed=400 + step + bar * 7) * gain, _at(bar, step * 0.5))

    # Koto run that fills the last bar and resolves into the loop.
    for i, name in enumerate(["A4", "C5", "D5", "E5", "G5", "A5", "G5", "E5"]):
        dsp.place_wrap(out, koto(NOTE[name], 0.45, seed=520 + i) * 0.7, _at(16, 2.0 + i * 0.25))

    # --- bass ------------------------------------------------------------
    for bar in range(3, BARS + 1):
        root = BASS_ROOT[PROGRESSION[bar - 1]]
        for beat, length in ((0.0, 1.0), (1.0, 1.0), (2.0, 1.0), (3.0, 1.0)):
            dsp.place_wrap(out, bass_note(NOTE[root], length * BEAT * 0.95) * 0.85, _at(bar, beat))
        dsp.place_wrap(out, bass_note(NOTE[root] * 1.5, BEAT * 0.5) * 0.4, _at(bar, 3.5))

    # --- melody ----------------------------------------------------------
    for bar, beat, name, length in MELODY_A + MELODY_B:
        dsp.place_wrap(out, shakuhachi(NOTE[name], length * BEAT * 0.98, seed=500 + bar) * 0.9, _at(bar, beat))
    # Final sustained note riding over the turnaround, wrapping the loop.
    dsp.place_wrap(out, shakuhachi(NOTE["A5"], 2.5, seed=599, vib=5.6) * 0.85, _at(16, 3.0))

    # --- accents ---------------------------------------------------------
    dsp.place_wrap(out, crash(), _at(3, 0.0))
    dsp.place_wrap(out, crash(seed=602) * 0.8, _at(9, 0.0))
    dsp.place_wrap(out, crash(seed=603) * 0.9, _at(16, 3.5))

    # A light overall reverb glues the kit to the room. Levelling happens in
    # write(), same as every other asset, so music sits under the hits.
    return dsp.reverb(out, room=0.16, decay=0.35)


def render_result_sting() -> np.ndarray:
    dur = 3.4
    out = np.zeros(int(dur * SR))
    gong = metal_hit(2.4, [
        (196.0, 1.1, 1.0), (293.0, 0.9, 0.7), (440.0, 0.7, 0.5),
        (587.0, 0.5, 0.35), (880.0, 0.35, 0.22), (1320.0, 0.22, 0.14),
    ], seed=701)
    dsp.place(out, dsp.reverb(gong * 0.7, room=0.45, decay=0.7), 0.0)
    dsp.place(out, taiko(110.0, 0.8, seed=702) * 1.0, 0.0)
    dsp.place(out, taiko(98.0, 0.7, seed=703) * 0.8, 0.46)
    dsp.place(out, taiko(124.0, 0.6, seed=704) * 0.7, 0.30)
    for i, name in enumerate(["A4", "C5", "E5", "A5", "C5", "E5", "A5", "E5"]):
        dsp.place(out, koto(NOTE[name], 0.9, seed=720 + i) * 0.55, 0.5 + i * 0.13)
    dsp.place(out, shakuhachi(NOTE["A5"], 1.6, seed=705) * 0.95, 1.1)
    dsp.place(out, crash(seed=706) * 1.0, 1.1)
    return master(out, -11.0, ceiling=0.92)


MUSIC = {
    "battle_loop": (render_battle_loop, True),
    "result_sting": (render_result_sting, False),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-reimport", action="store_true",
                    help="leave Godot's import cache alone (see tools/godot_reimport.py)")
    args = ap.parse_args()
    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(MUSIC)
    if args.list:
        for n in names:
            print(n)
        return 0
    for name in names:
        fn, looping = MUSIC[name]
        write(MUSIC_DIR / f"{name}.wav", fn(), -15.5, ceiling=0.9, fade_edges=not looping)
    # Without this the new music stays invisible to a game launched from the
    # command line - see tools/godot_reimport.py.
    if not args.only and not args.no_reimport:
        godot_reimport.reimport()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
