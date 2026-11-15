#!/usr/bin/env python3
"""Measure the rendered audio palette and fail if it drifts.

Rendering tools can only prove what they check. The first version of the sound
effects rendered, loaded and played back perfectly - and every punch still came
out as a muffled "boop", because nothing measured the thing that matters: where
the energy sits in the spectrum, and how loud the shout is next to the hit it
is covering.

So this tool treats the palette like a mix and asserts the intent behind each
sound:

  * impacts carry real top-end (2-8 kHz) so they read as strikes, not thuds
  * heavies and chakra have weight below 120 Hz so they land on any speaker
  * the crack is at the *front*: a hit whose overall balance is bright but
    whose first 25 ms is a dull thump still reads as a thump
  * swings and jumps are resonances, not hiss
  * the voice barks sit *under* the impacts they accompany
  * nothing clips, and nothing has a DC step

    python3 tools/audio_report.py            # table + PASS/FAIL, exit code
    python3 tools/audio_report.py --quiet    # only print failures
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "assets" / "audio"


# name -> what the sound has to be. `centroid` is the energy-weighted mean
# frequency in Hz; the band shares `sub` (<120 Hz), `body` (120-500 Hz), `mid`
# (0.5-2 kHz), `hf` (2-8 kHz) and `top` (>8 kHz) are percentages of total
# energy, and `_max` keys are upper bounds on a band.
#
# These are the palette's spec: tools/build_audio.py searches for mixes that
# satisfy them, so they have to describe the sound the player should hear, not
# just fence off the failures that were seen last time. The bands are therefore
# two-sided wherever the failure mode goes both ways - a guard clang can be dull
# or hissy, a swing can be a hiss instead of a resonance, a poof can be a thud
# instead of a puff - because a one-sided rule only ever pushes the search to
# the opposite corner. That is how the previous palette ended up with a clang
# made of 75% mid band and 17% metal: the rule it was written against only
# asked for "not too thin".
RULES = {
    # A jab is mostly crack: bright, no weight to speak of. "Thin" was the one
    # rule here with a single side - a ceiling on the low band and nothing under
    # the low-mid - and the search duly delivered a file with 71% of its energy
    # above 2 kHz and 9% between 120 and 500 Hz, which a listener named as a
    # menu confirm. The 2200 Hz centroid floor was doing the same damage from
    # the other side: any body added to the jab pulls the centroid down, so the
    # cheapest way to stay legal was to keep deleting the fist recording. Real
    # jabs sit at 1900-2400 Hz, and they have some low-mid meat.
    "hit_light":     {"centroid": (1900, 4400), "hf": (26, None), "sub": (None, 6),
                      "body": (12, 34), "mid_max": (38, None), "top_max": (9, None)},
    # A solid connect keeps the crack but adds a real body under it.
    "hit_medium":    {"centroid": (1400, 3200), "hf": (18, None), "sub": (2, 14),
                      "body": (16, None), "top_max": (11, None)},
    # A finisher returns the weight: most of the energy belongs low - but not
    # all of it. With a one-sided sub rule the first foley version put 41% of
    # its energy below 120 Hz against 8% between 2 and 8 kHz, and a listener
    # called it "hollow". Below 120 Hz is inaudible on the laptop speakers this
    # palette is mixed for, so the finisher has a ceiling as well as a floor.
    "hit_heavy":     {"centroid": (700, 2200),  "hf": (10, None), "sub": (4, 32),
                      "body": (18, None), "top_max": (10, None)},
    "launcher":      {"centroid": (1300, 3500), "hf": (16, None), "sub": (2, 14)},
    # Struck metal: the energy above 2 kHz *is* the clang.
    # The clang is the point, but a guard impact is still an impact: without a
    # floor on the low band the search throws the thump behind the metal away
    # and ships a hi-hat "tink" with 2.6% of its energy below 500 Hz.
    "block":         {"centroid": (2000, 4500), "hf": (26, None), "mid_max": (62, None),
                      "top_max": (12, None), "body": (4, None)},
    # Air moving past the listener is a resonance sweeping through the mid and
    # top, not a hiss: too much above 8 kHz reads as static.
    "whoosh_light":  {"centroid": (2500, 6500), "hf": (35, None), "sub": (None, 4),
                      "top_max": (9, None)},
    "whoosh_heavy":  {"centroid": (2000, 5200), "hf": (28, None), "sub": (None, 6),
                      "top_max": (9, None)},
    "dash":          {"centroid": (1200, 3800), "hf": (10, None), "sub": (None, 25)},
    "jump":          {"centroid": (2000, 5200), "hf": (22, None), "sub": (None, 6),
                      "top_max": (9, None)},
    # Smoke: airy with a soft hollow body, never a thud and never a hiss.
    "poof":          {"centroid": (1500, 4200), "hf": (12, None), "mid_max": (72, None),
                      "top_max": (8, None)},
    "land":          {"centroid": (700, 2600),  "hf": (5, None), "sub": (4, 22)},
    "chakra_charge": {"centroid": (400, 2600),  "sub": (5, None), "body": (18, None),
                      "mid": (18, None)},
    "chakra_shoot":  {"centroid": (1200, 3600), "hf": (16, None), "sub": (4, 20)},
    # An orb detonating is a boom with a crack, not a crack with a boom.
    # The sub band is two-sided on purpose: the floor is what makes the orb
    # land, but once the sweep dives fast and a sustained sine holds the bottom
    # the search will happily let 46 Hz take over the whole sound, and 39% of a
    # clip's energy below 120 Hz is inaudible on the laptop speakers this
    # palette is mixed for - the detonation has to keep its crack.
    "chakra_hit":    {"centroid": (700, 2400),  "sub": (9, 22), "hf": (4, None),
                      "mid": (18, None)},
    "ko":            {"centroid": (250, 1600),  "sub": (10, None), "hf": (2, 20)},
    "round_start":   {"centroid": (120, 800),   "sub": (6, 32), "body": (35, 85)},
    "time_up":       {"centroid": (220, 1000),  "body": (28, 75), "sub": (2, 28)},
}

# Sounds that only need the universal checks (present, finite, not clipping).
UNIVERSAL = ["round_start", "time_up", "ui_move", "ui_confirm", "aura_loop"]

VOICE_BURST_MAX = -6.0      # dBFS, loudest 20 ms window
VOICE_RMS_MAX = -14.0

# Share of energy above 2 kHz inside the first 25 ms of an impact. This is the
# window the ear reads as the crack of the strike, and it is the rule that the
# first palette failed most completely: a jab can measure a respectable overall
# centroid and still *begin* with a muffled thud.
#
# The head of a clip is measured with the same ideal-filter split as the rest of
# the spectrum (see `bands`), so this really is "how much of the energy in the
# first 25 ms is above 2 kHz" and not "how much survives a window that happens
# to be zero on the first sample".
ATTACK_RULES = {
    "hit_light": 40.0,
    "hit_medium": 30.0,
    "hit_heavy": 16.0,
    "launcher": 18.0,
    "block": 35.0,
    "land": 12.0,
    "chakra_shoot": 25.0,
    "chakra_hit": 18.0,
    "ko": 8.0,
}
ATTACK_WINDOW = 0.025


def load(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as f:
        channels, width, rate = f.getnchannels(), f.getsampwidth(), f.getframerate()
        raw = f.readframes(f.getnframes())
    if width != 2:
        raise ValueError(f"{path.name}: expected 16-bit PCM")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return x, rate


def bands(x: np.ndarray, rate: int) -> dict:
    """Energy distribution and centroid of a clip, in Hz and percent.

    The split is done with an ideal (brickwall) filter rather than a window:
    the clip is zero-padded, its power spectrum is taken, and the bins on each
    side of every corner frequency are summed. By Parseval that is exactly the
    energy the filter would pass, so the answer does not depend on *where* in
    the file the energy sits.

    That independence is the whole point. A single Hann-windowed FFT over a
    whole clip - what this function used to do - multiplies the first sample by
    zero and the middle by one, and every impact here starts at sample zero.
    The same boom measured 82% below 120 Hz sitting at the front of its own
    file and 59% once it started 0.3 s in; worse, a mix of layers with different
    lengths was scored mostly on whichever layer ran longest, so the renderer
    solved for a spectrum it could only reach by deleting the short low layers
    the targets were asking for. Fifteen of nineteen sounds came back "TARGET
    NOT REACHABLE" with their punch layers at zero gain, and the palette that
    resulted was exactly as thin and tail-heavy as those numbers said.

    The transform is taken at the clip's own length (rounded up to a power of
    two). Padding it four times over - the obvious way to keep the end of the
    clip from wrapping onto its start - changes no band share by more than
    0.6 pp on this palette, because every sound here is enveloped to silence at
    both edges and has nothing to wrap; the renderer calls this function
    thousands of times per sound, so it takes the 4x speed instead.
    """
    empty = {"centroid": 0.0, "sub": 0.0, "body": 0.0, "mid": 0.0, "hf": 0.0, "top": 0.0}
    if not len(x):
        return empty
    nfft = 1 << int(np.ceil(np.log2(max(len(x), 1024))))
    power = np.abs(np.fft.rfft(x, nfft)) ** 2
    freq = np.fft.rfftfreq(nfft, 1.0 / rate)
    total = float(power.sum()) + 1e-12

    def share(lo: float, hi: float) -> float:
        return 100.0 * float(power[(freq >= lo) & (freq < hi)].sum()) / total

    return {
        "centroid": float((freq * power).sum() / total),
        "sub": share(0.0, 120.0),
        "body": share(120.0, 500.0),
        "mid": share(500.0, 2000.0),
        "hf": share(2000.0, 8000.0),
        "top": share(8000.0, rate / 2.0),
    }


def above(x: np.ndarray, rate: int, split: float = 2000.0) -> float:
    """Percent of a clip's energy above `split` Hz, by the same ideal filter.

    Used for the attack gate, where the clip is a 25 ms head slice: this is the
    number the rule actually names, with no window shaping the answer.
    """
    if not len(x):
        return 0.0
    nfft = 1 << int(np.ceil(np.log2(max(len(x) * 4, 1024))))
    power = np.abs(np.fft.rfft(x, nfft)) ** 2
    freq = np.fft.rfftfreq(nfft, 1.0 / rate)
    return 100.0 * float(power[freq >= split].sum()) / (float(power.sum()) + 1e-12)


def burst_db(x: np.ndarray, win: float = 0.02, rate: int = 44100) -> float:
    """Loudness of the loudest short window - the measure the renderer levels on."""
    if not len(x):
        return -120.0
    n = max(1, min(len(x), int(win * rate)))
    power = np.square(x)
    cum = np.concatenate(([0.0], np.cumsum(power)))
    means = (cum[n:] - cum[:-n]) / n
    return 10.0 * np.log10(max(float(np.max(means)), 1e-12))


def rms_db(x: np.ndarray) -> float:
    if not len(x):
        return -120.0
    return 20.0 * np.log10(max(float(np.sqrt(np.mean(np.square(x)))), 1e-9))


def check(name: str, x: np.ndarray, rate: int, rules: dict, failures: list) -> dict:
    b = bands(x, rate)
    b["burst"] = burst_db(x, rate=rate)
    b["rms"] = rms_db(x)
    b["peak"] = float(np.max(np.abs(x))) if len(x) else 0.0
    b["dur"] = len(x) / rate
    b["dc"] = float(abs(np.mean(x))) if len(x) else 0.0
    b["clipped"] = int(np.sum(np.abs(x) >= 0.999))
    if name in ATTACK_RULES:
        window = min(len(x), max(64, int(ATTACK_WINDOW * rate)))
        if window < len(x):
            b["attack"] = above(x[:window], rate)

    def fail(msg: str) -> None:
        failures.append(f"{name}: {msg}")

    if b["peak"] < 0.05:
        fail(f"essentially silent (peak {b['peak']:.3f})")
    if b["clipped"] > 0:
        fail(f"{b['clipped']} clipped samples")
    if b["dc"] > 0.01:
        fail(f"DC offset {b['dc']:.3f}")
    if b["dur"] < 0.05:
        fail(f"too short to hear ({b['dur']:.3f}s)")

    for message, _ in rule_violations(name, b, rules):
        fail(message)
    return b


def rule_violations(name: str, b: dict, rules: dict | None = None) -> list[tuple[str, float]]:
    """Every way a measured sound misses the brief for its name.

    Returns `(description, magnitude)` pairs. The description is what the report
    prints; the magnitude is the same defect as a single number - percentage
    points of energy for the band and attack rules, octaves for the centroid -
    so `tools/build_audio.py` can search for a mix that has none of them.

    Sharing this between the renderer and the report is deliberate. The two used
    to keep separate tables describing what each sound should be: the renderer
    solved for its own hand-written *spectrum targets*, the report gated on
    these rules, and the two drifted apart until fifteen of nineteen sounds
    rendered "TARGET NOT REACHABLE" - i.e. the palette was optimised against a
    description the material could not satisfy, and nothing checked whether the
    result matched the brief.
    """
    if rules is None:
        rules = RULES.get(name, {})
    out: list[tuple[str, float]] = []

    if name in ATTACK_RULES:
        want = ATTACK_RULES[name]
        got = b.get("attack", 0.0)
        if got < want:
            out.append((f"dull attack: {got:.1f}% above 2 kHz in the first "
                        f"{ATTACK_WINDOW * 1000:.0f} ms, want >= {want:.0f}%",
                        1.2 * (want - got) / np.sqrt(want + 4.0)))

    for key, value in rules.items():
        if key == "centroid":
            lo, hi = value
            centroid = max(b["centroid"], 1.0)
            if centroid < lo:
                out.append((f"too dull: centroid {centroid:.0f} Hz, want >= {lo:.0f} Hz",
                            2.5 * float(np.log2(lo / centroid))))
            elif centroid > hi:
                out.append((f"too thin: centroid {centroid:.0f} Hz, want <= {hi:.0f} Hz",
                            2.5 * float(np.log2(centroid / hi))))
            continue
        lo, hi = value
        if key.endswith("_max"):
            band = key[:-4]
            got = b[band]
            if got > lo:
                out.append((f"too much {band}: {got:.1f}%, want <= {lo:.0f}%",
                            (got - lo) / np.sqrt(lo + 4.0)))
            continue
        got = b[key]
        if lo is not None and got < lo:
            out.append((f"missing {key}: {got:.1f}%, want >= {lo:.0f}%",
                        (lo - got) / np.sqrt(lo + 4.0)))
        elif hi is not None and got > hi:
            out.append((f"too much {key}: {got:.1f}%, want <= {hi:.0f}%",
                        (got - hi) / np.sqrt(hi + 4.0)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    failures: list[str] = []
    rows: list[tuple] = []

    sfx_dir = AUDIO / "sfx"
    names = [p.stem for p in sorted(sfx_dir.glob("*.wav"))]
    for name in names:
        x, rate = load(sfx_dir / f"{name}.wav")
        rows.append((name, check(name, x, rate, RULES.get(name, {}), failures)))

    voices: dict[str, dict] = {}
    for path in sorted((AUDIO / "voice").glob("*.wav")):
        x, rate = load(path)
        b = check("voice/" + path.stem, x, rate, {}, failures)
        voices[path.stem] = b
        if b["burst"] > VOICE_BURST_MAX:
            failures.append(f"voice/{path.stem}: shout peaks at {b['burst']:+.1f} dB, "
                            f"want <= {VOICE_BURST_MAX:+.1f} dB")
        if b["rms"] > VOICE_RMS_MAX:
            failures.append(f"voice/{path.stem}: shout averages {b['rms']:+.1f} dB, "
                            f"want <= {VOICE_RMS_MAX:+.1f} dB")

    # The mix rule that matters most: a bark must not bury the hit it lands on.
    # The runtime trims voices by 3 dB (scripts/sfx.gd) and leaves hits at 0, so
    # compare them after that trim.
    hit_light = next((b for n, b in rows if n == "hit_light"), None)
    if voices and hit_light is not None:
        loudest = max(b["burst"] for b in voices.values())
        margin = hit_light["burst"] - (loudest - 3.0)
        if margin < -2.0:
            failures.append(f"mix: the loudest shout lands {margin:+.1f} dB against the jab "
                            "(want no more than 2 dB over it)")

    if not args.quiet:
        print(f"{'sound':15}{'dur':>6}{'peak':>7}{'burst':>7}{'rms':>7}{'cent':>7}"
              f"{'>120':>7}{'120-500':>9}{'0.5-2k':>8}{'2-8k':>7}{'>8k':>6}{'attack':>8}")
        for name, b in rows:
            print(f"{name:15}{b['dur']:6.2f}{b['peak']:7.3f}{b['burst']:7.1f}{b['rms']:7.1f}"
                  f"{b['centroid']:7.0f}{b['sub']:7.1f}{b['body']:9.1f}{b['mid']:8.1f}"
                  f"{b['hf']:7.1f}{b['top']:6.1f}{b.get('attack', float('nan')):8.1f}")
        print(f"\n{'voice':15}{'dur':>6}{'peak':>7}{'burst':>7}{'rms':>7}{'cent':>7}")
        for name, b in sorted(voices.items()):
            print(f"{name:15}{b['dur']:6.2f}{b['peak']:7.3f}{b['burst']:7.1f}{b['rms']:7.1f}"
                  f"{b['centroid']:7.0f}")

    unreviewed = sorted(set(names) - set(RULES) - set(UNIVERSAL))
    if unreviewed:
        print("\n(no target rules for: %s)" % ", ".join(unreviewed))

    if failures:
        print(f"\nAUDIO REPORT FAIL: {len(failures)} issue(s)")
        for f in failures:
            print("  -", f)
        return 1
    print(f"\nAUDIO REPORT OK: {len(rows)} effects, {len(voices)} voice lines, all within target")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
