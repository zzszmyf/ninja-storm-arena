#!/usr/bin/env python3
"""Render the game's sound effects from scratch.

Every sound is synthesised with tools/dsp.py, so the project ships no sampled
or licensed audio. The palette is "late-90s TV anime fight scene": tight
cracky impacts, airy swept swings, a rising chakra charge, an energy blast with
a low core and a long tail, metallic guard clangs, a taiko-plus-gong round bell
and a big cartoon KO finish.

Two things decide whether a synthesised hit reads as a hit, and both were
wrong in the first version of this file:

  * Crack versus thud. An impact is a broadband click sitting on a short low
    sweep. Noise spreads its energy across the whole spectrum, so a crack that
    peaks as high as the sweep still measures ~20 dB down inside any single
    band - and the ear follows the energy, not the peak. Balanced by peak, the
    old punches came out as muffled "boop" tones with no snap: 96% of a jab's
    energy sat between 120 and 500 Hz. The crack layers now carry the weight
    they need, so a jab lands up in the 2-6 kHz region where a real strike
    lives.
  * Air is a resonance, not a hiss. A fixed band-pass turns noise into flat
    "shhh". Swings, jumps and dashes go through dsp.reson_sweep, a band pass
    whose centre frequency glides as the limb moves, which is the part the ear
    actually reads as movement.

A third problem outlived both: the layers were mixed by hand-picked weights,
and a weight is not a spectrum. A 250 Hz sine sweep holds roughly 40x the
energy of a 15 ms noise crack at the same peak, so weights of (0.22 snap,
0.63 punch) put 81% of a jab's energy between 120 and 500 Hz and the crack was
inaudible no matter how it was written. The palette is therefore *solved*
rather than weighted: `balance()` renders every layer, then searches for the
gains that put the mastered result on a target spectral distribution, measured
with the same maths tools/audio_report.py gates on. Low layers also had to be
rebuilt - see `thump()` for why the old booms never reached their own pitch.

`python3 tools/audio_report.py` measures both, plus the voice-versus-impact
mix, and fails if anything drifts back into the muddy or the hissy corner.

    python3 tools/build_audio.py                  # render everything
    python3 tools/build_audio.py --only hit_light,block
    python3 tools/build_audio.py --list
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np

import dsp
import foley
import godot_reimport
from audio_report import above, bands, rule_violations
from dsp import SR

ROOT = Path(__file__).resolve().parent.parent
SFX_DIR = ROOT / "assets" / "audio" / "sfx"
MUSIC_DIR = ROOT / "assets" / "audio" / "music"
VOICE_DIR = ROOT / "assets" / "audio" / "voice"

# Edge fades every shipped file gets. `balance()` applies these *before* it
# measures a candidate, so the spectrum the solver optimises is the spectrum the
# report will gate. It used to score the pre-fade signal and let `write` fade
# afterwards, which quietly invalidated every measurement: a 12 ms fade-out over
# a 140 ms jab moved its centroid from 3551 Hz to 2629 Hz and its top-end share
# from 28.3% to 25.0%, i.e. the solver "passed" the report's brightness gate by
# 3 points that no listener would ever hear, and the jab shipped failing it.
#
# The in-fade is a third of a millisecond - long enough to remove a DC step on
# sample zero, short enough that it cannot soften the crack of a strike, which
# is what a 1.5 ms fade in front of an impact that starts at sample zero does.
FADE_IN = 0.0004
FADE_OUT = 0.012

# The palette is band-limited on purpose, and this is the number that decides
# how "handheld anime fighter" it sounds rather than how hi-fi it sounds.
#
# Every impact here is built on noise, and noise has a flat spectrum: the
# 8-22 kHz band that tools/audio_report.py calls `top` spans 14 kHz, so a flat
# burst spends more of its energy up there than in the 2-8 kHz band that carries
# the crack - 8.7% of the guard clang and 8.7% of a light swing, which is the
# fizzy "tss" that makes synthesised combat audio sound cheap. The games this
# palette is chasing ran on hardware with an 8-bit DAC at 22-32 kHz; above
# roughly 8 kHz there was nothing to hear and nothing to synthesise. A two-pole
# roll-off there is what puts the energy back in the mid and crack bands, and it
# is applied inside `master()` so the mixer solves *through* it: the band shares
# the report gates on are the shares of the file that ships.
CONSOLE_TOP = 7800.0

# Which take of a sound is being rendered. Every noise source in this file goes
# through `noise()` below, which folds this into the seed, so a variant is the
# same move performed again - same layers, same tuning, different noise - rather
# than the same sample replayed. Take 0 is the canonical palette and is
# bit-identical to what this file rendered before takes existed; the extras are
# what stop a three-hit combo from sounding like a machine gun. See VARIANTS.
TAKE = 0


def noise(dur: float, seed: int = 0) -> np.ndarray:
    """`dsp.noise` with the current take folded into the seed."""
    return dsp.noise(dur, seed + TAKE * 7919)


# ------------------------------------------------------------------- foley

# The palette has two halves. The synth half is everything this file draws -
# the pitch-diving body under a punch, the ring of struck metal, the rising
# charge - and it is what the rules in tools/audio_report.py describe. The
# foley half is a recording: a real fist, a real metal clash, a real temple
# bell, taken from the CC0 packs that tools/foley.py installs under
# tools/foley/. Neither half is much use alone. A recording has the texture
# and the physics no oscillator reaches, and it has no idea it is in a game -
# so the synth layers give it the exaggeration (the deep drop, the bright
# crack, the room) that makes an anime hit read as an anime hit.
#
# `--palette synth` renders the file exactly as it was before the recordings
# arrived, which is the A side of docs/audio_ab.wav and the fallback when
# tools/foley/ has not been installed yet.
USE_FOLEY = True


def real(name: str, dur: float, take: int = 0, hp: float | None = None,
         lp: float | None = None, pitch: float = 0.0,
         fade: float | None = None, hp_stages: int = 1,
         lp_stages: int = 1) -> np.ndarray | None:
    """One take of a recorded sample, fitted to `dur` seconds.

    Returns None when the foley set is missing or switched off, and callers
    drop the layer - so a clone without the packs still renders the synth-only
    palette instead of failing.
    """
    if not USE_FOLEY:
        return None
    x = foley.take(name, take + TAKE)
    if x is None:
        return None
    if pitch:
        x = dsp.pitch_shift(x, pitch, keep_duration=True)
    # One pole is a 6 dB/octave slope, which is not enough to make a recorded
    # punch behave: high-passed once at 1.1 kHz, the fist still put 58% of a
    # jab's energy in the 120-500 Hz band and the solver could only satisfy its
    # centroid rule by deleting the recording. Filters stack.
    for _ in range(max(1, hp_stages)):
        if hp:
            x = dsp.onepole_hp(x, hp)
    for _ in range(max(1, lp_stages)):
        if lp:
            x = dsp.onepole_lp(x, lp)
    n = int(dur * SR)
    if len(x) > n:
        # Cutting a recording is how a 0.67 s punch becomes a 0.16 s jab, and
        # an unfaded cut leaves a step that reads as a second, quieter click.
        x = dsp.fade(x[:n], 0.0, fade if fade is not None else min(0.03, 0.2 * n / SR))
    elif len(x) < n:
        # A take that is shorter than the sound it is going under pads with
        # silence rather than failing: a layer is worth having even when it is
        # only the front of the sound, and a build that dies on a short sample
        # is a build nobody can run after swapping takes.
        x = np.concatenate([x, np.zeros(n - len(x))])
    return x


def with_real(layers: dict, key: str, name: str, dur: float, **kw) -> dict:
    """Add a recorded layer to a mix, or leave the mix alone without foley."""
    x = real(name, dur, **kw)
    if x is not None:
        layers[key] = x
    return layers


# ------------------------------------------------------------------ helpers

def click(dur: float, hp: float, decay: float, seed: int = 7, gain: float = 1.0,
          lp: float = 12000.0) -> np.ndarray:
    """The crack of a strike: broadband noise with the bottom rolled away.

    This is the layer that carries an impact through a small speaker. Almost
    all of a punch's perceived "hit" lives above 1 kHz; without it the sound is
    just a thud.

    The decay is deliberately in the tens, not the hundreds: a 1 ms impulse
    measures as a spike and then gets crushed by the master ceiling, which is
    how the crack layer of the first version ended up inaudible. A real jab's
    crack lasts 10-25 ms.
    """
    n = noise(dur, seed)
    top = dsp.onepole_hp(n, hp)
    top = dsp.onepole_lp(top, lp)  # stop the noise floor fizzing
    return top * dsp.env_ad(dur, 0.0006, decay) * gain


def crack(dur: float, centre: float, decay: float, q: float = 1.2, seed: int = 7,
          gain: float = 1.0) -> np.ndarray:
    """A band-limited noise transient - the mid 'smack' under the click."""
    n = noise(dur, seed)
    return dsp.bandpass(n, centre, q) * dsp.env_ad(dur, 0.0004, decay) * gain


def tick(dur: float, hp: float, decay: float, seed: int = 7, gain: float = 1.0,
         stages: int = 2, lp: float = 8000.0, lp_stages: int = 2) -> np.ndarray:
    """The sharpest layer of a strike: a click built by rolling off, not by tuning.

    `crack` is a band pass, so it has a floor as well as a ceiling and always
    puts part of its energy in the 0.5-2 kHz band - fine for a smack, wrong for
    the tick of a knuckle or a metal rim, which should live almost entirely
    above 4 kHz. Successive one-pole high passes roll the bottom away without
    the resonant ring a band pass gives, and the decay is the shortest in the
    palette: the click is 6-10 ms and gone.
    """
    n = noise(dur, seed)
    for _ in range(max(1, stages)):
        n = dsp.onepole_hp(n, hp)
    # The roll-off is deliberately below the 8 kHz gate and applied twice: a
    # single pole at 9 kHz is still only half a dB down at 8 kHz, which left
    # 66% of a tick's energy above the gate - brightness bought with fizz that
    # reads as static, the one thing the top-end caps in tools/audio_report.py
    # exist to stop. Everything the ear hears as "crack" is 2-8 kHz.
    for _ in range(max(1, lp_stages)):
        n = dsp.onepole_lp(n, lp)
    return n * dsp.env_ad(dur, 0.0002, decay) * gain


def thud(dur: float, f0: float, f1: float, decay: float, curve: float = 2.0) -> np.ndarray:
    """The body of an impact: a fast downward sine sweep."""
    return dsp.sweep(f0, f1, dur, curve) * dsp.env_ad(dur, 0.001, decay)


def body(dur: float, centre: float, decay: float, seed: int = 5, q: float = 0.9) -> np.ndarray:
    """Low-mid weight for impacts.

    Noise-only hits read as fizzy 'tss' because almost all of their energy sits
    above 2 kHz. A band of filtered noise around 200-500 Hz is what makes a
    punch land like a punch instead of like static.
    """
    return dsp.bandpass(noise(dur, seed), centre, q) * dsp.env_ad(dur, 0.001, decay) * 1.4


def sub(dur: float, f0: float, f1: float, decay: float, curve: float = 1.5) -> np.ndarray:
    """Chest thump. Kept out of the way of the mid band, felt more than heard."""
    return dsp.sweep(f0, f1, dur, curve) * dsp.env_ad(dur, 0.002, decay)


def thump(dur: float, f0: float, f1: float, decay: float, curve: float = 1.0) -> np.ndarray:
    """A low body thump: a short sine sweep that actually arrives at its pitch.

    This exists because the old booms did not. `sub(0.9, 160, 38, 6.5)` sweeps
    for 900 ms while its envelope is gone in 60, so by the time the tone has
    fallen anywhere near the bottom of the sweep it is already 40 dB down: the
    low band measured empty and every "deep" hit was really a 200 Hz blip. A
    chest thump has to finish its drop inside the first few tens of
    milliseconds, which is what this helper is for.
    """
    return dsp.sweep(f0, f1, dur, curve) * dsp.env_ad(dur, 0.0015, decay)


def air(dur: float, f0: float, f1: float, q: float = 2.0, curve: float = 1.5,
        shape: float = 1.6, seed: int = 3, gain: float = 1.0) -> np.ndarray:
    """A limb moving through air: a resonance sweeping past the listener."""
    n = noise(dur, seed)
    return dsp.reson_sweep(n, f0, f1, q, curve) * dsp.env_swell(dur, shape) * gain


def hiss(dur: float, hp: float, lp: float, shape: float = 1.6, seed: int = 4,
         gain: float = 1.0) -> np.ndarray:
    """Supporting broadband air, kept well under the resonance."""
    return dsp.onepole_lp(dsp.onepole_hp(noise(dur, seed), hp), lp) * dsp.env_swell(dur, shape) * gain


def metal_hit(dur: float, partials, seed: int = 11, attack: float = 0.0005,
              excite: float = 900.0, ring: bool = False,
              tilt: float | None = None) -> np.ndarray:
    """Struck metal: a noise burst fed through a bank of tuned resonators.

    `attack` and `excite` shape the strike itself. A very short excitation makes
    every partial start in phase and the sum spikes 18 dB above its own body,
    which the master ceiling then has to squash - that is why the first temple
    bell measured quieter than a whoosh. A few milliseconds of contact spread
    over a few cycles rings the same partials without the spike.

    `ring` switches from the filtering resonator to true modal synthesis (see
    dsp.modal), which is what a bell or a gong needs. It is off by default so
    the music, which was signed off separately, keeps the exact timbre it had.

    `tilt` re-levels the bank to a dB-per-octave amplitude slope measured from
    the lowest partial, and without it a metal bank is nothing like as bright
    as its partials suggest. A modal mode's impulse response is
    `r^n sin((n+1)w0)/sin(w0)`, so its peak carries a `1/sin(w0)` weight: a
    210 Hz mode comes out about 21x hotter than a 4.5 kHz one, i.e. roughly
    -12 dB per octave before the decays tilt it further. The guard clang was
    written with six partials out to 5.3 kHz and still measured a 886 Hz
    centroid with 0.0% of its energy above 2 kHz - a wooden knock, which is
    the one thing a metal guard impact must not be. A positive tilt of about
    +8 dB/octave cancels the bias and lands the bank up where it belongs.
    """
    src = noise(dur, seed) * dsp.env_ad(dur, attack, excite)
    out = np.zeros_like(src)
    base = min(p[0] for p in partials) if tilt is not None else 0.0
    for i, (freq, decay, gain) in enumerate(partials):
        if tilt is not None:
            gain = gain * 10.0 ** (tilt * np.log2(freq / base) / 20.0)
        # Stagger the modes slightly so they do not all start in phase and sum
        # into a spike on the very first sample.
        excite_at = (i % 3) * (0.0012 if ring else 0.0)
        layer = dsp.place(np.zeros_like(src), src.copy(), excite_at)
        fn = dsp.modal if ring else dsp.resonator
        out += fn(layer, freq, decay) * gain
    return out


def unit(x: np.ndarray) -> np.ndarray:
    """Normalise a layer to unit RMS so mixes can be written as proportions."""
    r = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    return x / r if r > 1e-9 else x


def late(x: np.ndarray, seconds: float) -> np.ndarray:
    """Delay a layer by a couple of milliseconds.

    A real strike is a crack with the body arriving a hair behind it. When every
    layer of a hit starts on sample zero they all sum into one blob and the
    crack stops reading as a separate event, which is a large part of what makes
    a synthesised punch sound like a synth and not like a punch. Two or three
    milliseconds is enough to separate them, and short enough that the body is
    still inside the 25 ms window the report calls the attack.
    """
    n = int(seconds * SR)
    return np.concatenate([np.zeros(n), x]) if n > 0 else x


def energy_burst(dur: float, seed: int = 21) -> np.ndarray:
    """Bright filtered noise with a fast attack, used inside chakra effects."""
    n = noise(dur, seed)
    return dsp.onepole_hp(n, 900.0) * dsp.env_ad(dur, 0.0012, 16.0)


def swoosh(dur: float, f0: float, f1: float, curve: float = 1.6, shape: float = 1.5,
           seed: int = 3, noise_gain: float = 1.0, gain: float = 1.0) -> np.ndarray:
    """Air moving past the listener: formants gliding over turbulent noise.

    The first version was pure filtered noise, which measured as hiss; the fix
    was to add three sine harmonics gliding together with the sweep - and that
    fixed the measurement and broke the sound. A glide of harmonics *is* a
    pitch, so every swing, jump and dash in the game announced itself with a
    chirp, the single most recognisable "this was made by a synthesiser" tell
    there is. Record a limb or a blade moving through air and there is no
    fundamental at all: there is noise, plus one or two resonances that the
    body of the moving thing drags through it.

    So the harmonics are gone. The layers here are two `reson_sweep` bands -
    a lower formant and an upper one about an octave and a half up, gliding
    together - multiplied by a slow noise envelope so the air is turbulent
    rather than a smooth hiss. What is left of the old tone is one whisper of
    the fundamental at 12%: enough to keep a swing present on a laptop
    speaker, far too little to be heard as a note.
    """
    n = int(dur * SR)
    if n <= 0:
        return np.zeros(0)
    t = np.linspace(0.0, 1.0, n) ** curve
    phase = np.cumsum(2.0 * np.pi * (f0 + (f1 - f0) * t) / SR)
    low = dsp.reson_sweep(noise(dur, seed), f0, f1, 1.7, curve)
    # The upper formant is what the ear hears as the *speed* of the swing: a
    # hand sweeps a wide band, a blade a narrow one, and both put more energy
    # into the second formant than into the first.
    high = dsp.reson_sweep(noise(dur, seed + 11), f0 * 2.6, f1 * 2.4, 2.1, curve)
    turb = dsp.onepole_lp(noise(dur, seed + 23), 55.0)
    turb = 0.78 + 0.5 * turb / max(float(np.max(np.abs(turb))), 1e-9)
    env = dsp.env_swell(dur, shape)
    body = (low + 0.42 * high) * turb
    return (body * noise_gain + np.sin(phase) * 0.12) * env * gain


def tame(x: np.ndarray, cutoff: float = 10500.0) -> np.ndarray:
    """Roll off the top octave so the noise layers stop hissing."""
    return dsp.onepole_lp(x, cutoff)


def master(x: np.ndarray, target_db: float, ceiling: float = 0.95, max_drive: float = 3.0) -> np.ndarray:
    """Hit a loudness target, adding soft saturation only as far as needed.

    A crisp 0.15 s jab has a huge peak-to-average ratio, so peak normalisation
    always leaves it quiet next to a long boom. Here the sound is first placed
    at the target; if the peak ceiling makes that impossible, a binary search
    finds the lightest amount of soft clipping that lifts the body of the sound
    up to where it belongs. Light clipping on impacts is a feature - it is how
    real fighting-game hits get their bite - but it is applied least-first so
    tailed sounds like the gong stay clean.
    """
    # Modal resonators have a DC term that outlives the sound: the bell's own
    # impulse response is r^n sin((n+1)w0), whose sum over a two-second decay at
    # 311 Hz is a real offset, and it was showing up as a 0.02 DC step on the
    # end-of-round gong. A one-pole high-pass at 22 Hz removes it and is far
    # below anything the palette puts out on purpose.
    x = dsp.onepole_hp(x, 22.0)
    x = dsp.onepole_lp(dsp.onepole_lp(x, CONSOLE_TOP), CONSOLE_TOP)
    plain = dsp.level(x, target_db, ceiling)
    if dsp.burst_db(plain) >= target_db - 0.25:
        return plain
    # The target is measured on the loudest 20 ms window, so a sound with a very
    # sharp transient can be impossible to place there without hitting the
    # ceiling. Soft clipping first flattens the transient into the body, which
    # is exactly what a hit needs; search for the least drive that lands the
    # target, and keep whichever candidate got closest if none does.
    lo, hi, best = 1.0, max_drive, None
    fallback, fallback_db = plain, dsp.burst_db(plain)
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        candidate = dsp.level(dsp.saturate(x, mid), target_db, ceiling)
        burst = dsp.burst_db(candidate)
        if burst > fallback_db:
            fallback, fallback_db = candidate, burst
        if burst >= target_db - 0.25:
            # Feasible: remember it, and look for a lighter drive that also is.
            best = candidate
            hi = mid
        else:
            lo = mid
    return best if best is not None else fallback


def write(
    path: Path,
    data: np.ndarray,
    target_db: float = -18.0,
    ceiling: float = 0.95,
    fade_edges: bool = True,
    mastered: bool = False,
) -> None:
    # `balance()` has to level the sound it measures, so anything it returns is
    # already at its target; only the hand-built sounds are mastered here.
    if not mastered:
        data = master(data, target_db, ceiling)
    if fade_edges:
        data = dsp.fade(data, FADE_IN, FADE_OUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(dsp.to_int16(data).tobytes())
    print(f"  {path.relative_to(ROOT)}  {len(data) / SR:.2f}s  burst {dsp.burst_db(data):+.1f} dB")


# -------------------------------------------------------------------- mixing

# How each sound is built, in the order the ear hears it. `defaults` is the mix
# the sound designer wants, as a proportion of each layer's RMS: normally the
# transient that defines the hit first, then its body, then support. `room`,
# `decay` and `tame` shape every layer of that sound before the mix, and `drive`
# is the saturation on the mix bus.
#
# These numbers are the sound. `balance()` may move them, but only as far as it
# takes to satisfy the rules in tools/audio_report.py - and it is pulled back
# toward these proportions while it does.
#
# Earlier versions of this file instead described every sound as a hand-written
# *spectrum* to solve for. The renderer could not reach most of those spectra -
# the material simply does not contain those proportions - so it spent its whole
# search budget thrashing, reported "TARGET NOT REACHABLE" on fifteen of
# nineteen sounds, deleted the layers it could not fit, and shipped whatever it
# found on the way out. The numbers were never checked against the report's own
# rules, so a palette that had been "solved" still failed nine of them.
CHARACTER = {
    "hit_light": {
        # `tame` at 9.5 kHz and not 13.5: the top octave of a 150 ms jab is
        # 8-10 kHz fizz, which is the "high-pitched fizzle" the review heard
        # behind the transient, and the console roll in master() only starts at
        # 7.8 kHz. `room` comes up from 0.10 because a jab thrown in a room has
        # one short tail behind it, and the layers need a shared space to sit in.
        "room": 0.14, "decay": 0.26, "tame": 9500.0, "drive": 1.15,
        "defaults": {"fist": 1.10, "snap": 1.00, "tick": 0.90, "crack": 1.00,
                     "smack": 0.30, "meat": 0.55, "punch": 0.50, "chest": 0.40},
    },
    "hit_medium": {
        "room": 0.18, "decay": 0.34, "tame": 10500.0, "drive": 1.30,
        "defaults": {"fist": 1.10, "snap": 0.70, "tick": 0.55, "crack": 1.00,
                     "smack": 0.85, "meat": 0.55, "punch": 0.75, "chest": 0.55,
                     "push": 0.25},
    },
    "hit_heavy": {
        "room": 0.30, "decay": 0.50, "tame": 10000.0, "drive": 1.45,
        "defaults": {"fist": 1.00, "plate": 0.85, "snap": 0.70, "tick": 0.60,
                     "crack": 0.70, "smack": 1.00, "meat": 0.55, "punch": 0.75,
                     "boom": 1.00, "ring": 0.20, "debris": 0.40},
    },
    "launcher": {
        "room": 0.30, "decay": 0.46, "tame": 10500.0, "drive": 1.45,
        "defaults": {"fist": 0.90, "edge": 0.55, "snap": 0.60, "crack": 0.85,
                     "meat": 0.55, "shing": 0.55, "punch": 0.85, "boom": 0.70,
                     "rise": 0.60},
    },
    "block": {
        "room": 0.22, "decay": 0.40, "tame": 14000.0, "drive": 1.10,
        "defaults": {"clash": 1.00, "clatter": 0.45, "clang": 1.00, "tick": 0.85,
                     "crack": 0.35, "thump": 0.40, "chest": 0.30},
    },
    "whoosh_light": {
        "room": 0.14, "decay": 0.26, "tame": 15000.0, "drive": 1.0,
        "defaults": {"whip": 1.00, "bright": 0.85, "air": 0.30},
    },
    "whoosh_heavy": {
        "room": 0.22, "decay": 0.36, "tame": 15000.0, "drive": 1.0,
        "defaults": {"whip": 1.00, "bright": 0.80, "air": 0.35, "weight": 0.30},
    },
    "dash": {
        "room": 0.22, "decay": 0.34, "tame": 12000.0, "drive": 1.25,
        "defaults": {"whip": 1.00, "air": 0.50, "surge": 0.80, "push": 0.45},
    },
    "poof": {
        "room": 0.24, "decay": 0.32, "tame": 15000.0, "drive": 1.0,
        "defaults": {"pop": 0.90, "puff": 1.00, "breath": 0.80, "hollow": 0.70,
                     "bright": 0.30},
    },
    "jump": {
        "room": 0.12, "decay": 0.24, "tame": 15000.0, "drive": 1.0,
        "defaults": {"lift": 1.00, "bright": 0.70, "spring": 0.60, "cloth": 0.50,
                     "scuff": 0.45},
    },
    "land": {
        "room": 0.20, "decay": 0.35, "tame": 11500.0, "drive": 1.2,
        "defaults": {"foot": 1.00, "snap": 0.60, "crack": 0.70, "punch": 0.90,
                     "chest": 0.70, "dust": 0.60, "thud": 0.80},
    },
    "chakra_charge": {
        "room": 0.30, "decay": 0.50, "tame": 13000.0, "drive": 1.20,
        "defaults": {"field": 0.70, "rise": 1.00, "stack": 0.80, "shimmer": 0.70,
                     "sparkle": 0.40, "spin": 0.50, "low": 0.40, "harm": 0.55},
    },
    "chakra_shoot": {
        "room": 0.26, "decay": 0.44, "tame": 13500.0, "drive": 1.25,
        "defaults": {"edge": 0.60, "snap": 0.70, "core": 1.00, "tone": 0.70,
                     "push": 0.50, "launch": 0.80, "flutter": 0.35},
    },
    "chakra_hit": {
        "room": 0.36, "decay": 0.54, "tame": 12000.0, "drive": 1.45,
        "defaults": {"blast": 0.90, "crunch": 0.35, "snap": 0.60, "burst": 0.80,
                     "down": 0.70, "core": 1.00, "boom": 1.00, "floor": 0.55,
                     "crackle": 0.45, "ring": 0.55},
    },
    "ko": {
        "room": 0.45, "decay": 0.70, "tame": 12000.0, "drive": 1.60,
        "defaults": {"crunch": 0.55, "blast": 0.70, "punch": 1.00, "boom": 1.00,
                     "snap": 0.50, "crack": 0.70, "wobble": 0.60, "bounce": 0.70},
    },
    "round_start": {
        "room": 0.35, "decay": 0.60, "tame": 12000.0, "drive": 1.40,
        "defaults": {"bell": 0.60, "taiko": 1.00, "gong": 0.60, "sticks": 0.50},
    },
    "time_up": {
        "room": 0.45, "decay": 0.80, "tame": 13000.0, "drive": 1.10,
        "defaults": {"bell_real": 0.70, "bell": 1.00, "body": 0.50, "hum": 0.40,
                     "strike": 0.50},
    },
}

# Bus glue, per sound: one gain envelope driven by the *sum* of the layers, so a
# crack, a smack and a thump stop reading as three files that start together.
# See dsp.glue for the settings; `thr` is in multiples of the sound's own RMS.
#
# The two bells are the exception and are switched off. Their tail is the whole
# sound, so an envelope driven by the sum rides the ring down instead of the
# transient, and a compressor that pumps a two-second gong is a compressor that
# has made the palette worse. Everything percussive gets it.
GLUE = {
    "hit_light": {"window": 0.0012, "thr": 1.5, "ratio": 3.2},
    "hit_medium": {"window": 0.0014, "thr": 1.5, "ratio": 3.0},
    "hit_heavy": {"window": 0.0018, "thr": 1.6, "ratio": 2.8},
    "launcher": {"window": 0.0016, "thr": 1.6, "ratio": 2.8},
    "block": {"window": 0.0012, "thr": 1.5, "ratio": 3.2},
    "land": {"window": 0.0014, "thr": 1.5, "ratio": 3.0},
    "jump": {"window": 0.0014, "thr": 1.6, "ratio": 2.6},
    "dash": {"window": 0.0020, "thr": 1.7, "ratio": 2.4},
    "poof": {"window": 0.0016, "thr": 1.6, "ratio": 2.6},
    "chakra_shoot": {"window": 0.0014, "thr": 1.6, "ratio": 2.8},
    "chakra_hit": {"window": 0.0018, "thr": 1.6, "ratio": 2.8},
    "ko": {"window": 0.0020, "thr": 1.7, "ratio": 2.6},
    "whoosh_light": {"window": 0.0020, "thr": 1.8, "ratio": 2.2},
    "whoosh_heavy": {"window": 0.0022, "thr": 1.8, "ratio": 2.2},
}


def shares(x: np.ndarray, rate: int = SR) -> dict:
    """Percentage of energy per band, from the report's own analyser."""
    b = bands(x, rate)
    return {k: b[k] for k in ("sub", "body", "mid", "hf", "top")}


def attack_brightness(x: np.ndarray, win: float = 0.025, rate: int = SR) -> float:
    """Share of energy above 2 kHz in the first `win` seconds of a sound.

    Uses the report's ideal-filter split rather than a windowed FFT, so the
    first few milliseconds of a crack - the part that makes a hit read as a hit
    - are measured at full weight instead of being tapered away by a window
    that is zero on its first sample.
    """
    n = min(len(x), int(win * rate))
    if n < 64:
        return 0.0
    return above(x[:n], rate)


def _shape(x: np.ndarray, cfg: dict) -> np.ndarray:
    """Room and tone shaping for one layer. Both steps are linear."""
    return dsp.reverb_lin(tame(x, cfg["tame"]), cfg["room"], cfg["decay"])


# A mix that already satisfies its rules is free to sit anywhere, so pull it
# gently back toward the designer's proportions.
REGULARISATION = 0.08

# ...but a violation has to outrank the tidy-up, and on the raw scale it did
# not. A miss of 0.2 percentage points of top end costs 0.0013, and a gain
# nudged 13% back toward the designer's proportions costs the same 0.0013 - so
# the descent could trade a miss for a straighter mix and stop there. Eight
# sounds shipped that way, each sitting a hair outside its own brief: hit_light
# 3 Hz below its centroid floor, block 0.2 points short of its top end, poof
# 8 Hz dull. Nothing was wrong with the rules or the material; the two halves
# of the objective were simply on the same scale. Weighting the rule term past
# anything the regularisation can offer makes feasibility the first priority
# and leaves the tidy-up in charge only once there is nothing left to fix.
VIOLATION_WEIGHT = 1000.0


def _cost(x: np.ndarray, name: str, gains: dict, defaults: dict) -> float:
    """How far a mixed sound is from its brief.

    The brief is the rules in tools/audio_report.py - the same ones the report
    gates the rendered files on - plus "stay near the mix the designer asked
    for". Both halves matter: rules alone let a passing mix drift anywhere,
    defaults alone never fix anything.
    """
    b = bands(x, SR)
    b["attack"] = attack_brightness(x)
    cost = VIOLATION_WEIGHT * sum(
        magnitude ** 2 for _message, magnitude in rule_violations(name, b)
    )
    cost += REGULARISATION * sum(
        float(np.log(max(gains[k], 1e-6) / max(defaults[k], 1e-6))) ** 2 for k in gains
    )
    return cost


def balance(name: str, layers: dict, floors: dict | None = None,
            verbose: bool = True) -> np.ndarray:
    """Mix `layers` to `name`'s brief and master the result.

    Starts from the proportions in CHARACTER[name]["defaults"] and runs a
    coordinate descent over the per-layer gains, scoring the *mastered* sound.
    Because every fixed step - filter, room, level - is applied per layer first
    and is linear, the shaped sum is the sum of the shaped layers, so a
    candidate mix costs one addition and one soft clip to evaluate.

    `floors` names the layers the mix may not throw away, as a minimum share of
    the loudest layer: `{"ring": 0.30}` keeps the ring at 30% of whatever the
    dominant layer ends up at. Rules describe a sound's spectrum, and a spectrum
    cannot say "keep the ring of the struck guard" or "keep the dizzy wobble at
    the end of the KO" - those live in time. Without a floor the search deletes
    them to reach a number five percent sooner.
    """
    cfg = CHARACTER[name]
    level_db = LEVELS.get(name, -16.0)
    mats = {k: unit(_shape(v, cfg)) for k, v in layers.items()}
    length = max(len(m) for m in mats.values())
    floors = {k: v for k, v in (floors or {}).items() if k in mats}
    defaults = {k: float(cfg["defaults"].get(k, 1.0)) for k in mats}

    def pin(gains: dict) -> dict:
        """Raise every floored layer to its share of the loudest layer.

        One pass is enough: a floor is below 1.0, so lifting a layer to
        `floor * top` can never make it the new loudest layer, which is what
        would otherwise need the whole thing to be iterated to a fixed point.
        """
        out = dict(gains)
        top = max(out.values())
        for key, floor in floors.items():
            if out[key] < floor * top:
                out[key] = floor * top
        return out

    # The descent revisits the same pinned mixes over and over (a trial that the
    # floors undo is the state it started from), and each evaluation costs an
    # FFT, so remember the renders. This is what makes a full rebuild take
    # seconds instead of minutes.
    cache: dict = {}

    def render(g: dict) -> np.ndarray:
        key = tuple(round(g[k], 9) for k in mats)
        hit = cache.get(key)
        if hit is None:
            hit = _render(g)
            if len(cache) < 8192:
                cache[key] = hit
        return hit

    def _render(g: dict) -> np.ndarray:
        x = np.zeros(length)
        for key, layer in mats.items():
            x[: len(layer)] += layer * g[key]
        # Pin the mix bus before the soft clip. Shares are scale-free, so
        # without this the gains are only defined up to a common factor, and the
        # search "improves" the spectrum by driving one layer into hard
        # distortion instead of by mixing - which is how the first solver run
        # turned every swing into a clipped 240 Hz tone. Normalising on RMS
        # rather than peak keeps a fixed, audible amount of limiting: a spiky
        # crack gets squashed enough to reach its loudness target, a dense boom
        # barely touches the knee.
        rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
        bus = x / max(rms, 1e-12)
        glue = GLUE.get(name)
        if glue:
            bus = dsp.glue(bus, **glue)
        out = master(dsp.saturate(bus, cfg["drive"]), level_db)
        # Score the file, not an intermediate: the report loads what `write`
        # put on disk, edges faded. See FADE_IN / FADE_OUT.
        return dsp.fade(out, FADE_IN, FADE_OUT)

    def descend(start: dict) -> tuple[dict, float]:
        gains = pin(start)
        best = _cost(render(gains), name, gains, defaults)
        # Two passes over the same coordinate descent: a coarse one that finds
        # which corner of the mix the sound belongs in, then a fine one that
        # settles onto the boundary of the brief instead of next to it.
        #
        # One coarse pass was not enough, and the way it failed was quiet. A
        # rule miss costs `VIOLATION_WEIGHT` times its square, so the search
        # always *tries* to fix a violation - but a 1.27x step is too big to
        # land on a boundary it is already resting against, so it rounded the
        # corner off and stopped. The jab came back 0.7 points over its mid
        # ceiling, 0.6 points short of its body floor and 0.4 points short of
        # its attack floor: three rules, each missed by a step size. A 1.05x
        # step after the coarse pass closes them, and the boundary itself is
        # where these mixes sound right - a jab *is* mostly crack.
        for grid in (np.geomspace(0.10, 6.0, 18), np.geomspace(0.78, 1.28, 13)):
            for _ in range(4):
                moved = False
                for key in mats:
                    base = gains[key]
                    best_state, best_cost = gains, best
                    for factor in grid:
                        # Score the pinned candidate, not the raw one, so the cost
                        # never rewards a move the floors would undo.
                        trial = pin({**gains, key: base * factor})
                        cost = _cost(render(trial), name, trial, defaults)
                        if cost < best_cost - 1e-9:
                            best_state, best_cost, moved = trial, cost, True
                    gains, best = best_state, best_cost
                if not moved:
                    break
        return gains, best

    # Two deterministic starts: the designer's mix, and a bright-biased one.
    # Coordinate descent has no way back out of a corner, and a start that is
    # already failing a rule can be sitting in one.
    start_bright = {k: defaults[k] * (1.0 + (shares(m)["hf"] + shares(m)["top"]) / 12.0)
                    for k, m in mats.items()}
    gains, best = descend(defaults)
    other, other_cost = descend(start_bright)
    if other_cost < best:
        gains, best = other, other_cost

    out = render(gains)
    if verbose:
        top = max(gains.values())
        mix = "  ".join(f"{k} {gains[k] / top:.2f}" for k in mats)
        b = bands(out, SR)
        b["attack"] = attack_brightness(out)
        broken = rule_violations(name, b)
        note = "" if not broken else "   <- " + "; ".join(m for m, _ in broken)
        print(f"    mix  {mix}{note}")
        print(f"         cent {b['centroid']:5.0f} Hz   sub {b['sub']:4.1f}  body {b['body']:4.1f}"
              f"  mid {b['mid']:4.1f}  hf {b['hf']:4.1f}  top {b['top']:4.1f}"
              f"   attack>2k {b['attack']:4.1f}%   cost {best:.2f}")
    return out


# ------------------------------------------------------------------- sounds

def sfx_hit_light() -> np.ndarray:
    """Jab: a recorded fist, a knuckle crack, and the meat it lands on.

    The review of the previous version was one line - "a sharp, thin smack
    followed by a high-pitched fizzle; reads as a menu confirm" - and it is an
    accurate description of what the layers added up to: 71% of the file sat
    between 2 and 8 kHz and 9% between 120 and 500. That is a tick, not a
    knuckle. Two things were wrong. The crack bank was voiced an octave too
    high (3.2 kHz and up, which is where a notification lives), and the fist
    recording had been filtered down to nothing: three poles of high pass at
    2 kHz kept the solver honest about the recording but threw away the contact
    noise the layer exists for, so the layer contributed a click and no body.
    The cracks are ~700 Hz lower, the fist is high-passed at 1.1 kHz with two
    poles, and the low-mid that was missing arrives as a `meat` band at 780 Hz
    plus the chest thump.
    """
    dur = 0.16
    layers = {
        # Every layer of the jab is band-limited. The broadband `click` that
        # used to be the snap put 40% of its own energy above 8 kHz while the
        # solver kept buying brightness there - a jab is a knuckle on a ribcage,
        # not static.
        # The bank sits *above* the report's 2 kHz split on purpose. A knuckle
        # crack voiced at 1.5-1.9 kHz measures as mid band, and the mid band is
        # the 500 Hz - 2 kHz "cardboard box" region that made the first version
        # of this jab read as a click: 49% of the file landed there against a
        # 38% ceiling. The crack layers are 2.1 kHz and up, the body is at
        # 380 Hz and below, and the muffled 500-1.5 kHz region is deliberately
        # close to empty - which is also how a real jab is equalised.
        "snap": crack(dur, 3200.0, 38.0, 1.4, seed=1),
        "tick": crack(dur, 2500.0, 30.0, 1.25, seed=14),
        "crack": crack(dur, 2100.0, 24.0, 1.10, seed=2),
        # The mid "thwack". It stays small: 500 Hz - 2 kHz is the band that
        # makes a hit sound like a cardboard box, and the first attempt at this
        # jab let it take 58% of the file.
        "smack": crack(dur, 700.0, 16.0, 0.85, seed=3),
        # The "thock" of a fist on a ribcage, at 430 Hz so it lands in the band
        # the jab is allowed to have some of. Its floor is what stops the solver
        # from tuning the jab back into a click by deleting it.
        "meat": late(body(dur, 380.0, 18.0, seed=4, q=1.05), 0.001),
        "punch": late(thud(dur, 260.0, 130.0, 26.0), 0.002),
        "chest": late(thump(0.10, 165.0, 88.0, 20.0), 0.002),
    }
    # The fist itself: low-passed at 9 kHz because the pack's condenser mic
    # brought its own noise floor along, high-passed at 1.1 kHz because a
    # recording of a real punch is mostly low end and the body of it would fight
    # the one thing a jab has to be, which is crack. Two poles, not three: the
    # third one was removing the contact transient.
    with_real(layers, "fist", "punch_light", 0.12, take=0, hp=1100.0, lp=9000.0,
              hp_stages=2, pitch=3.0)
    return balance("hit_light", layers,
                   floors={"fist": 0.32, "meat": 0.22, "chest": 0.20})


def sfx_hit_medium() -> np.ndarray:
    """Solid connect: a recorded punch under more weight, grit and a push of air."""
    dur = 0.28
    layers = {
        "snap": click(dur, 2100.0, 40.0, seed=5, lp=8000.0),
        "tick": crack(dur, 2600.0, 34.0, 1.3, seed=16),
        "crack": crack(dur, 1150.0, 26.0, 1.05, seed=6),
        "smack": crack(dur, 600.0, 16.0, 0.85, seed=7),
        "meat": late(body(dur, 700.0, 13.0, seed=17, q=1.0), 0.001),
        "punch": late(thud(dur, 210.0, 84.0, 20.0), 0.003),
        "chest": late(thump(0.13, 145.0, 52.0, 17.0), 0.003),
        "push": hiss(dur, 1200.0, 7000.0, shape=1.6, seed=8, gain=0.5),
    }
    # Same treatment as the jab, one notch lower: a solid connect is allowed
    # twice the body of a jab by its brief, so the recording keeps its weight
    # from 600 Hz up rather than 1.1 kHz.
    with_real(layers, "fist", "punch_heavy", dur, take=1, hp=600.0, lp=11000.0)
    return balance("hit_medium", layers,
                   floors={"fist": 0.45, "meat": 0.22, "chest": 0.25,
                           "snap": 0.30})


def sfx_hit_heavy() -> np.ndarray:
    """Finisher impact: recorded fist on a plate, deep boom, debris tail.

    The previous version rang. Six modes from 210 Hz to 6.4 kHz with a quarter
    of a second of decay is a bell in a game whose guard impact is also a bell,
    and the review of the rendered file heard exactly that: "a metallic clang
    that sounds more like a successful block than a heavy hit". The modes are
    now four dull ones below 400 Hz with short decays, the metal that is left
    comes from a recorded heavy plate rather than a tuned bank, and the weight a
    finisher needs is carried by the fist, the boom and the debris.
    """
    dur = 0.5
    ring = metal_hit(dur, [(96.0, 0.10, 1.0), (148.0, 0.08, 1.0),
                           (236.0, 0.06, 1.0), (388.0, 0.04, 0.70)], seed=9,
                     attack=0.002, excite=900.0, ring=True, tilt=4.0)
    layers = {
            "snap": click(dur, 1800.0, 26.0, seed=13),
            # A bright tick above the fist: 41% of the energy in the first
            # version of this file sat below 120 Hz and 8% between 2 and 8 kHz,
            # which is what "a muddy explosion" is as a measurement.
            "tick": crack(dur, 3100.0, 22.0, 1.2, seed=19),
            "crack": crack(dur, 780.0, 14.0, 0.85, seed=9),
            "smack": crack(dur, 340.0, 8.0, 0.8, seed=10),
            "meat": late(body(dur, 620.0, 9.0, seed=11, q=0.9), 0.002),
            "punch": late(thud(dur, 175.0, 55.0, 11.0, curve=1.5), 0.004),
            "boom": late(thump(0.26, 125.0, 38.0, 7.0), 0.004),
            "ring": ring,
    }
    with_real(layers, "fist", "punch_heavy", dur, take=0, lp=12000.0)
    # A recorded heavy plate under the fist: the metal a finisher is allowed to
    # have is the sound of something buckling, not of something ringing.
    with_real(layers, "plate", "plate_heavy", 0.30, take=0, hp=500.0, lp=9000.0)
    # Rubble instead of filtered noise: the tail of a finisher is where a synth
    # layer is most obviously a synth layer, because a decaying noise burst has
    # no events in it. The pack's mining impact is a recording of things
    # breaking, so the tail has grit that actually moves.
    with_real(layers, "debris", "rock", dur, take=0, lp=7000.0)
    return balance("hit_heavy", layers,
                   floors={"fist": 0.45, "plate": 0.35, "ring": 0.10,
                           "boom": 0.45, "debris": 0.25, "crack": 0.30,
                           "snap": 0.35, "tick": 0.25})


def sfx_launcher() -> np.ndarray:
    """Third-hit blow-away: recorded strike under a metal shing and a launched body.

    This was reviewed as "a very bright metallic chime that rings out, followed
    by a deeper bassy slam - the chime is too slow and melodic for an impact and
    the slam is disconnected from it". Both halves were true: the shing was six
    modes with up to 0.34 s of decay, i.e. a melodic chime, and it opened the
    sound, so the blow-away announced itself with a note before anyone heard a
    fist. The shing is now a short, lower, denser bank that starts on the same
    sample as the strike, and the recorded fist and metal edge carry the front.
    """
    dur = 0.70
    shing = metal_hit(dur, [
        (1050.0, 0.16, 1.0), (1480.0, 0.13, 1.0), (2180.0, 0.10, 1.0),
        (3150.0, 0.07, 0.90), (4500.0, 0.05, 0.70), (6200.0, 0.03, 0.50),
    ], seed=17, attack=0.0015, excite=1200.0, ring=True, tilt=6.0)
    rise = dsp.place(np.zeros(int(dur * SR)),
                     dsp.sweep(320.0, 1150.0, 0.42, 1.8) * dsp.env_ad(0.42, 0.004, 9.0), 0.03)
    layers = {
            "snap": click(0.3, 2200.0, 30.0, seed=14),
            "crack": crack(0.45, 820.0, 14.0, 1.0, seed=15),
            "meat": late(body(0.4, 640.0, 10.0, seed=18, q=0.95), 0.002),
            "shing": shing,
            "punch": late(thud(0.5, 200.0, 62.0, 14.0), 0.004),
            # The blow-away is a body being thrown, so it needs a little weight
            # under the metal shing; the sweep dives fast (curve < 1) so the
            # low band actually fills before the envelope is gone.
            "boom": late(thump(0.22, 118.0, 38.0, 9.0, curve=0.6), 0.004),
            "rise": rise,
    }
    with_real(layers, "fist", "punch_heavy", 0.45, take=1, lp=11000.0)
    # A bright metal rim on top of the fist: this is the hit that is supposed to
    # sound like the fight is being won, so it gets a blade-on-blade edge the
    # other two hits do not have.
    with_real(layers, "edge", "metal_medium", 0.4, take=1, hp=450.0, lp=12000.0)
    return balance("launcher", layers,
                   floors={"fist": 0.35, "edge": 0.28, "shing": 0.16,
                           "rise": 0.12, "boom": 0.25, "meat": 0.18})


def sfx_whoosh_light() -> np.ndarray:
    """Fast jab swing: one narrow resonance sweeping up past 2 kHz."""
    dur = 0.20
    bright = dsp.reson_sweep(noise(dur, 26), 2500.0, 6000.0, 1.5, 1.4) \
        * dsp.env_swell(dur, 1.6)
    return balance(
        "whoosh_light",
        {
            "whip": swoosh(dur, 700.0, 2800.0, curve=1.5, shape=1.4, seed=21, noise_gain=0.5),
            "bright": bright,
            # The supporting air stops at 8 kHz: past that a swing stops being
            # air and becomes tape hiss. See the top-end caps in audio_report.
            "air": hiss(dur, 3000.0, 8000.0, shape=1.8, seed=22, gain=0.6),
        },
        floors={"whip": 0.50},
    )


def sfx_whoosh_heavy() -> np.ndarray:
    """Wide finisher swing: a slower, lower sweep with real body behind it."""
    dur = 0.34
    bright = dsp.reson_sweep(noise(dur, 26), 2000.0, 6000.0, 1.6, 1.5) \
        * dsp.env_swell(dur, 1.5)
    return balance(
        "whoosh_heavy",
        {
            "whip": swoosh(dur, 380.0, 1500.0, curve=1.6, shape=1.3, seed=23, noise_gain=0.55),
            "bright": bright,
            # A wide band pass rather than a high pass: the swing needs energy
            # between 2 and 8 kHz to read as air, and the last thing it needs is
            # the 8 kHz-plus tail a high-passed noise layer drags in with it.
            "air": dsp.bandpass(noise(dur, 24), 4000.0, 0.75) * dsp.env_swell(dur, 1.6),
            "weight": body(dur, 240.0, 9.0, seed=25),
        },
        floors={"whip": 0.50},
    )


def sfx_dash() -> np.ndarray:
    """Air dash: a resonance whipping past over recorded air displacement."""
    dur = 0.42
    layers = {
            "whip": swoosh(dur, 320.0, 1800.0, curve=1.7, shape=1.5, seed=31, noise_gain=0.5),
            "air": hiss(dur, 1800.0, 9000.0, shape=1.8, seed=32, gain=0.5),
            # The surge is short on purpose: a 130 -> 62 Hz sweep stretched over
            # the whole 0.42 s never gets below 110 Hz before it decays away.
            "surge": thump(0.16, 130.0, 62.0, 9.0),
    }
    # The body of air a dash pushes. It sits under the sweep rather than beside
    # it: `soft_heavy` is a low, wide recording, which is what makes the move
    # read as mass moving and not as a noise burst with a filter on it.
    with_real(layers, "push", "soft_heavy", dur, take=0, lp=5000.0)
    return balance("dash", layers, floors={"whip": 0.40, "push": 0.35})


def sfx_poof() -> np.ndarray:
    """Smoke puff - shadow-clone / substitution flavour."""
    dur = 0.42
    layers = {
            "puff": swoosh(dur, 2000.0, 430.0, curve=0.8, shape=1.2, seed=33, noise_gain=0.75),
            "breath": dsp.onepole_lp(noise(dur, 34), 1900.0) * dsp.env_ad(dur, 0.006, 9.0),
            "hollow": body(dur, 420.0, 8.0, seed=35),
            "bright": hiss(dur, 2400.0, 8000.0, shape=1.2, seed=36, gain=0.35),
    }
    # A substitution is a *pop* of displaced air, and that pop is a recorded
    # one: the pack's soft impact has the plosive front and the loose, dusty
    # tail a puff of smoke needs. Low-passed at 6 kHz so it stays smoke and
    # does not turn into another transient.
    with_real(layers, "pop", "soft_heavy", dur, take=1, lp=6000.0)
    return balance("poof", layers, floors={"pop": 0.45, "hollow": 0.40})


def sfx_block() -> np.ndarray:
    """Guard: two recorded clangs plus the synth ring of struck metal.

    Both the partials and the excitation have to be bright. Struck with a
    450 Hz-band excitation and nothing ringing above 3.6 kHz, the old clang
    measured a 554 Hz centroid with 0.1% of its energy above 2 kHz - a dull
    wooden knock, which is the one thing a guard impact must not sound like.

    The bank also used to stop at 9.6 kHz with a +7.5 dB/octave tilt, which
    still left the clang 6 points short of the metal share its brief asks for
    and two thirds of the sound sitting in the 0.5-2 kHz "wooden" band. Guard
    metal rings well past 10 kHz, so the bank now reaches 12.5 kHz, the tilt is
    steeper, and the mid smack under it is a `tick` rather than a band-passed
    `crack` that could only add to the band that was already too full.
    """
    dur = 0.34
    strike = metal_hit(dur, [
        (760.0, 0.26, 0.80), (1140.0, 0.24, 0.80), (1720.0, 0.22, 0.95),
        (2600.0, 0.19, 1.0), (3900.0, 0.16, 1.0), (5300.0, 0.13, 1.0),
        (7200.0, 0.10, 1.0), (9600.0, 0.07, 1.0),
    ], seed=31, attack=0.0008, excite=3600.0, ring=True, tilt=8.5)
    layers = {
            "clang": strike,
            "tick": tick(dur, 4200.0, 60.0, seed=36, lp=9500.0),
            "crack": crack(dur, 2200.0, 26.0, 1.2, seed=37),
            "thump": late(thud(dur, 160.0, 70.0, 24.0), 0.002),
            "chest": late(thump(0.10, 150.0, 62.0, 16.0), 0.002),
    }
    # A guard is a kunai on a kunai, and no amount of tuned partials gets there:
    # the modes ring, the recording *clatters*. Two of them, so the clash has
    # the two contacts a real block has (the block and the bounce), and the
    # synth ring keeps the sustain on top.
    with_real(layers, "clash", "metal_light", dur, take=1, hp=700.0)
    with_real(layers, "clatter", "tin_medium", 0.25, take=0, hp=400.0)
    return balance("block", layers,
                   floors={"clash": 0.45, "clatter": 0.25, "clang": 0.35,
                           "tick": 0.30})


def sfx_chakra_charge() -> np.ndarray:
    """Rising energy: a swelling drone, a real reactor hum, shimmering sparks."""
    dur = 1.05
    t = dsp.t_axis(dur)
    ramp = np.linspace(0.0, 1.0, int(dur * SR))
    # Harmonics in the 200-700 Hz window are what keep a charge audible on a
    # laptop speaker; the pure sub drone of the first version vanished there.
    stack = (dsp.sine(220.0, dur) * 0.50 + dsp.sine(330.0, dur) * 0.33
             + dsp.sine(440.0, dur) * 0.22) * (ramp ** 1.8)
    # The 120-500 Hz stack above is what survives a laptop speaker, but the
    # charge also needs harmonics in the 0.5-2 kHz band or it reads as a hum
    # with a hiss on top rather than as gathering energy - it measured 17.9%
    # against an 18% floor. These two partials ride the same swell, an octave
    # up, and give the solver a lever that is not just "more noise".
    harm = (dsp.sine(660.0, dur) * 0.60 + dsp.sine(990.0, dur) * 0.40) * (ramp ** 2.4)
    trem = 0.6 + 0.4 * np.sin(2 * np.pi * 9.0 * t)
    layers = {
            "rise": dsp.sweep(85.0, 640.0, dur, 2.2) * (ramp ** 2.2),
            "stack": stack,
            "shimmer": air(dur, 900.0, 4600.0, q=2.2, curve=2.0, shape=1.8, seed=41),
            "sparkle": hiss(dur, 2500.0, 11000.0, shape=1.8, seed=42),
            "harm": harm,
            "spin": dsp.sine(320.0, dur) * trem * (ramp ** 2.0),
            "low": dsp.sine(58.0, dur) * dsp.env_swell(dur, 1.2),
    }
    # A recorded sci-fi field hum under the stack. Every synth layer here is a
    # steady tone, and a sound made only of steady tones is a chord; the
    # recording is what moves, breathes and crackles, so the charge sounds like
    # it is coming from something rather than being played on a keyboard.
    with_real(layers, "field", "force_field", dur, take=0, lp=7000.0)
    return balance("chakra_charge", layers,
                   floors={"stack": 0.30, "rise": 0.20, "field": 0.30})


def sfx_chakra_shoot() -> np.ndarray:
    """Release: a bright attack, a band sweeping down, a low launch."""
    dur = 0.5
    flutter = dsp.bandpass(noise(dur, 54), 1800.0, 0.8)
    flutter = flutter * (0.55 + 0.45 * np.sin(2 * np.pi * 28.0 * dsp.t_axis(dur)))
    layers = {
            "snap": click(0.12, 2400.0, 45.0, seed=53),
            "core": dsp.reson_sweep(noise(dur, 51), 2000.0, 350.0, q=1.6, curve=1.5)
                    * dsp.env_ad(dur, 0.004, 11.0),
            "tone": dsp.sweep(900.0, 190.0, dur, 1.3) * dsp.env_ad(dur, 0.004, 12.0),
            "push": energy_burst(dur, seed=52),
            "launch": thump(0.13, 120.0, 45.0, 12.0),
            "flutter": flutter,
    }
    # The release itself: a bright recorded metal hit, high-passed so only its
    # edge survives. It is the difference between "a filtered noise burst" and
    # "something was pushed out of a hand".
    with_real(layers, "edge", "metal_scifi", 0.28, take=0, hp=800.0)
    return balance("chakra_shoot", layers,
                   floors={"core": 0.35, "edge": 0.30, "launch": 0.18})


def sfx_chakra_hit() -> np.ndarray:
    """Energy orb detonating against a fighter: recorded blast under a deep core.

    The low end was the problem. `boom` swept 145 -> 36 Hz over 0.55 s with an
    envelope that is already 39 dB down a quarter of the way in, and because a
    `thump` sweep is linear in time it had only fallen to ~110 Hz by then - so
    the layer that was supposed to be the detonation's weight never produced
    anything below 120 Hz at an audible level, and the orb measured a 4.7% sub
    share against a 9% floor. The sweep now dives with `curve < 1` (fast at the
    start) and a sustained 46 Hz sine holds the floor underneath it, which is
    what an orb going off actually does on a small speaker.
    """
    dur = 0.8
    ring = metal_hit(dur, [(420.0, 0.14, 1.0), (1050.0, 0.10, 1.0),
                           (2100.0, 0.07, 1.0), (3900.0, 0.05, 1.0)],
                     seed=64, attack=0.001, excite=1500.0, ring=True, tilt=10.0)
    layers = {
            "snap": click(0.18, 2400.0, 40.0, seed=63),
            "burst": energy_burst(dur, seed=61),
            "down": dsp.sweep(900.0, 70.0, 0.35, 1.1) * dsp.env_ad(0.35, 0.002, 10.0),
            "core": late(thump(0.14, 140.0, 44.0, 10.0), 0.002),
            # The detonation has to keep its floor for a good part of its
            # length, or the sound is a bright fizz with a 100 ms blip under it.
            # This is the layer that makes the orb land on a laptop speaker.
            "boom": late(thump(0.50, 140.0, 34.0, 5.5, curve=0.55), 0.002),
            "floor": dsp.sine(46.0, dur) * dsp.env_ad(dur, 0.006, 3.4),
            "crackle": dsp.onepole_hp(noise(0.45, 62), 3200.0) * dsp.env_ad(0.45, 0.006, 6.0),
            "ring": ring,
    }
    # The explosion is a recording now. `lowFrequency_explosion` is the weight
    # (a real one has a long, uneven rumble that a single sine sweep cannot
    # imitate), `crunch` is the debris leaving the impact, and a metal hit on
    # top is the crack the orb makes when it touches armour rather than air.
    #
    # The blast is high-passed at 140 Hz before it is allowed in. A recording
    # of an explosion is 90% energy below 120 Hz, and the report's sub ceiling
    # exists because that band is inaudible on a laptop speaker: at its natural
    # balance the recording took the detonation to 46% sub and the floor layer
    # - the one that is supposed to make the orb land - could not be heard as
    # anything but weight. Two poles at 140 Hz keep the rumble and hand the
    # bandwidth back to the crack.
    with_real(layers, "blast", "boom_low", dur, take=0, hp=140.0, hp_stages=2,
              lp=6000.0)
    with_real(layers, "crunch", "crunch", 0.55, take=0, lp=9000.0)
    with_real(layers, "edge", "metal_scifi", 0.28, take=1, hp=900.0)
    # The recorded layers keep real floors - they are the ones that carry the
    # texture - and the synthetic sub layers keep small ones. A floor on a
    # 46 Hz sine is a floor on exactly the band the report caps, so the solver
    # can only obey the cap by making the rest of the sound louder, and past a
    # point that is a bright fizz with a boom stapled to it.
    return balance("chakra_hit", layers,
                   floors={"blast": 0.16, "crunch": 0.30, "edge": 0.18,
                           "core": 0.16, "boom": 0.18, "floor": 0.08,
                           "ring": 0.15})


def sfx_jump() -> np.ndarray:
    """Take-off: a recorded scuff and push under the synth lift."""
    dur = 0.22
    layers = {
            "lift": swoosh(dur, 520.0, 1900.0, curve=1.4, shape=1.3, seed=71, noise_gain=0.45),
            "bright": hiss(dur, 2500.0, 8000.0, shape=1.5, seed=73, gain=0.7),
            "spring": dsp.sweep(240.0, 600.0, dur, 1.4) * dsp.env_ad(dur, 0.004, 18.0),
            "cloth": dsp.onepole_lp(noise(dur, 72), 2200.0) * dsp.env_swell(dur, 1.5),
    }
    # The foot leaving the floor. High-passed hard, because a jump is the light
    # move in the game and the pack's concrete footstep has a low thump in it
    # that would make every jump read as a landing.
    with_real(layers, "scuff", "step_hard", 0.16, take=1, hp=900.0, lp=9000.0)
    return balance("jump", layers, floors={"lift": 0.40, "scuff": 0.25})


def sfx_land() -> np.ndarray:
    """Touchdown: a recorded footfall carrying the whole sound."""
    dur = 0.28
    layers = {
        "snap": click(dur, 1800.0, 45.0, seed=83),
        "crack": crack(dur, 900.0, 22.0, 1.0, seed=84),
        "punch": late(thud(dur, 140.0, 52.0, 14.0), 0.003),
        "chest": late(body(dur, 240.0, 13.0, seed=82), 0.003),
        "dust": dsp.onepole_lp(noise(dur, 81), 1500.0) * dsp.env_ad(dur, 0.003, 11.0),
        "thud": late(thump(0.09, 120.0, 48.0, 18.0), 0.003),
    }
    # `step_hard` is the layer that was missing: this sound is a boot hitting
    # ground, so it gets a floor of its own and the synth layers work around it.
    with_real(layers, "foot", "step_hard", dur, take=0)
    return balance("land", layers, floors={"foot": 0.50})


def sfx_ko() -> np.ndarray:
    """Big cartoon finish: recorded blast, ring-out, then the dizzy wobble."""
    dur = 1.60
    # dizzy descending wobble
    n = int(0.9 * SR)
    t = np.linspace(0.0, 1.0, n)
    glide = np.exp(np.log(520.0) + (np.log(140.0) - np.log(520.0)) * t)
    phase = np.cumsum(2 * np.pi * glide / SR)
    vib = 0.35 * np.sin(2 * np.pi * 6.5 * dsp.t_axis(0.9))
    wob = (np.sin(phase + vib) * 0.6 + np.sin(phase * 1.5) * 0.25) * dsp.env_ad(0.9, 0.05, 3.0)
    wobble = dsp.place(np.zeros(int(dur * SR)), wob, 0.42)
    bounce = dsp.place(np.zeros(int(dur * SR)), thud(0.4, 90.0, 40.0, 14.0), 1.02)
    layers = {
            "punch": thud(0.9, 200.0, 40.0, 6.0, curve=1.5),
            "boom": thump(0.35, 130.0, 34.0, 6.0),
            "snap": click(0.5, 2000.0, 9.0, seed=91),
            "crack": crack(0.6, 900.0, 6.0, 0.9, seed=92),
            "wobble": wobble,
            "bounce": bounce,
    }
    with_real(layers, "crunch", "crunch", 1.0, take=1, lp=9500.0)
    with_real(layers, "blast", "boom_low", dur, take=1)
    # The dizzy wobble after the boom is the joke; without it the KO is a
    # generic explosion and the solver is happy to delete it.
    return balance("ko", layers,
                   floors={"wobble": 0.25, "bounce": 0.15,
                           "crunch": 0.30, "blast": 0.35})


def sfx_round_start() -> np.ndarray:
    """Taiko hits into a recorded temple bell - the 'hajime!' moment."""
    dur = 1.70
    taiko = np.zeros(int(dur * SR))
    sticks = np.zeros(int(dur * SR))
    for at, gain in ((0.0, 1.0), (0.30, 0.75), (0.60, 1.05)):
        dsp.place(taiko, dsp.mix(
            thud(0.55, 120.0, 44.0, 11.0, 1.4) * 1.1,
            dsp.sine(62.0, 0.45) * dsp.env_ad(0.45, 0.002, 12.0) * 0.6,
        ), at, gain)
        # The stick on the drum skin, kept as its own layer: it is the only part
        # of a taiko that lives above the drum's own 100-200 Hz body, and folded
        # into the drum the solver is free to throw it away.
        dsp.place(sticks, dsp.mix(
            crack(0.30, 1400.0, 12.0, 1.0, seed=101, gain=0.7),
            click(0.2, 2400.0, 22.0, seed=103, gain=0.5),
        ), at, gain)
    # `ring=True` matters here: the unit-peak `resonator` the music uses makes
    # a two-second mode a thousand times quieter than a one-millisecond one, so
    # a bell built on it is a click with no tone. Modal partials let the strike
    # set the level and the decay only set how long it rings.
    gong = dsp.place(np.zeros(int(dur * SR)), metal_hit(1.2, [
        (196.0, 1.10, 0.80), (293.0, 1.00, 0.70), (415.0, 0.95, 0.62),
        (587.0, 0.85, 0.55), (880.0, 0.70, 0.42), (1245.0, 0.55, 0.30),
        (2130.0, 0.35, 0.20), (3200.0, 0.22, 0.12),
    ], seed=102, attack=0.003, excite=900.0, ring=True, tilt=5.0), 0.60)
    layers = {"taiko": taiko, "gong": gong, "sticks": sticks}
    # A struck bell recorded in a room, sitting under the synth gong. It is one
    # of the two sounds in the palette that are recognisably *an instrument*
    # rather than an effect, and tuned modes on their own always came out
    # slightly glassy next to it.
    with_real(layers, "bell", "bell_heavy", dur, take=0, lp=11000.0)
    return balance("round_start", layers,
                   floors={"gong": 0.35, "sticks": 0.20, "bell": 0.30})


def sfx_time_up() -> np.ndarray:
    """Temple bell for the end of the round: a recording under the tuned modes."""
    dur = 2.2
    bell = metal_hit(dur, [
        (311.0, 1.80, 0.62), (466.0, 1.70, 0.58), (622.0, 1.60, 0.55),
        (933.0, 1.40, 0.48), (1244.0, 1.20, 0.40), (1866.0, 1.00, 0.32),
        (2790.0, 0.75, 0.22), (4150.0, 0.50, 0.12),
    ], seed=111, attack=0.004, excite=900.0, ring=True)
    # The struck body of the bell. The resonators ring, but on their own the
    # first 20 ms is all strike and no tone, so the loudest window measures far
    # below the tail that follows it.
    body_tone = (dsp.sine(311.0, dur) * 0.5 + dsp.sine(466.0, dur) * 0.22) \
        * dsp.env_ad(dur, 0.004, 1.6, curve=1.4)
    # A temple bell's hum tone sits an octave below its strike tone; without it
    # the whole sound is 300-500 Hz and there is nothing for a small speaker to
    # reproduce as weight.
    hum = dsp.sine(103.8, dur) * dsp.env_ad(dur, 0.01, 1.3, curve=1.4)
    layers = {
            "bell": bell,
            "body": body_tone,
            "hum": hum,
            "strike": click(0.25, 2300.0, 26.0, seed=112),
    }
    with_real(layers, "bell_real", "bell_heavy", dur, take=1, lp=11000.0)
    return balance("time_up", layers,
                   floors={"bell_real": 0.35, "bell": 0.40, "hum": 0.12})


def sfx_ui_move() -> np.ndarray:
    """Menu blip: the arcade chirp, roughened by a recorded tick."""
    dur = 0.10
    layers = [
        dsp.sine(1180.0, dur) * dsp.env_ad(dur, 0.002, 34.0) * 0.5,
        dsp.sine(1760.0, dur) * dsp.env_ad(dur, 0.002, 44.0) * 0.25,
    ]
    tick = real("ui_tick", dur, take=0, hp=1200.0)
    if tick is not None:
        layers.append(tick * 0.55)
    return dsp.mix(*layers)


def sfx_ui_confirm() -> np.ndarray:
    """Confirm: a rising tone with a real UI click under it."""
    dur = 0.28
    layers = [
        dsp.sweep(880.0, 1320.0, dur, 1.0) * dsp.env_ad(dur, 0.003, 16.0) * 0.6,
        dsp.sine(2200.0, dur) * dsp.env_ad(dur, 0.002, 26.0) * 0.2,
    ]
    click = real("ui_confirm", dur, take=0, hp=600.0)
    if click is not None:
        layers.append(click * 0.5)
    return dsp.mix(*layers)


def sfx_aura_loop() -> np.ndarray:
    """Seamless chakra hum played while a fighter is flying."""
    dur = 1.60
    t = dsp.t_axis(dur)
    lfo = 0.7 + 0.3 * np.sin(2 * np.pi * 0.9 * t)
    drone = (dsp.sine(110.0, dur) * 0.5 + dsp.sine(165.0, dur) * 0.30 + dsp.sine(221.5, dur) * 0.18)
    hiss_layer = dsp.bandpass(noise(dur, 121), 2100.0, 0.9) * 0.20 * lfo
    hum = (drone * lfo + hiss_layer) * 0.5
    # A field hum that is already a loop: it is the only layer here that moves
    # on its own, which is what stops a sustained flight sound from reading as
    # a held organ note. It is a five-second engine bed cut to the loop length
    # rather than the sub-second `force_field`, because the aura plays for as
    # long as the player holds the button and a 0.95 s take cut to 1.6 s would
    # be half silence - which is a stutter, not a hum.
    field = real("engine_low", dur, take=1, lp=7000.0, fade=0.12)
    if field is not None:
        hum = hum + field * 0.6
    return dsp.loopify(hum, cross=0.25)


SFX = {
    "hit_light": sfx_hit_light,
    "hit_medium": sfx_hit_medium,
    "hit_heavy": sfx_hit_heavy,
    "launcher": sfx_launcher,
    "whoosh_light": sfx_whoosh_light,
    "whoosh_heavy": sfx_whoosh_heavy,
    "dash": sfx_dash,
    "poof": sfx_poof,
    "block": sfx_block,
    "chakra_charge": sfx_chakra_charge,
    "chakra_shoot": sfx_chakra_shoot,
    "chakra_hit": sfx_chakra_hit,
    "jump": sfx_jump,
    "land": sfx_land,
    "ko": sfx_ko,
    "round_start": sfx_round_start,
    "time_up": sfx_time_up,
    "ui_move": sfx_ui_move,
    "ui_confirm": sfx_ui_confirm,
    "aura_loop": sfx_aura_loop,
}

# Target loudness per sound, in dBFS of the loudest 20 ms window (see
# dsp.burst_db). This table *is* the mix: it decides how forward each sound sits
# in the game, so a jab stays audible next to a finisher and the utility sounds
# sit politely underneath. Numbers are relative to the loudest event (the KO
# boom at -2.5 dB), i.e. a -13 dB whoosh is about 10 dB under a hit.
LEVELS = {
    "hit_light": -9.0,
    "hit_medium": -6.5,
    "hit_heavy": -4.0,
    "launcher": -4.5,
    "whoosh_light": -13.5,
    "whoosh_heavy": -10.5,
    "dash": -10.0,
    "poof": -11.5,
    "block": -7.0,
    "chakra_charge": -11.0,
    "chakra_shoot": -5.5,
    "chakra_hit": -4.0,
    "jump": -13.0,
    "land": -9.0,
    "ko": -2.5,
    "round_start": -5.5,
    "time_up": -6.0,
    "ui_move": -20.0,
    "ui_confirm": -13.0,
    "aura_loop": -13.5,
}

# The voice barks are rendered by tools/gen_voices.py and arrive peak
# normalised, which left every shout about 5 dB *louder* than the jab it was
# covering (measured -11 dB RMS against the hit's -20 dB). They are re-levelled
# here on RMS - the measure that decides how loud a sustained shout is - with a
# separate cap on the loudest 20 ms so a bark still cannot step on its impact.
# Levelling on the burst alone is what left the old shouts at -12 dB RMS, i.e.
# 2 dB over the report's ceiling and clearly over the hit they accompany.
VOICE_RMS_DB = -15.5
VOICE_BURST_DB = -9.0
VOICE_CEILING = 0.90


def level_rms(x: np.ndarray, target_db: float, ceiling: float = 0.95) -> np.ndarray:
    """`dsp.level`, but matching average level instead of the loudest window."""
    if not len(x):
        return x
    x = x * (10.0 ** ((target_db - dsp.rms_db(x)) / 20.0))
    peak = float(np.max(np.abs(x)))
    return x * (ceiling / peak) if peak > ceiling else x


def polish_voices() -> None:
    """Trim and re-level every installed voice bark in place."""
    for path in sorted(VOICE_DIR.glob("*.wav")):
        with wave.open(str(path), "rb") as f:
            channels, rate = f.getnchannels(), f.getframerate()
            raw = f.readframes(f.getnframes())
        if rate != SR:
            continue
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
        if channels > 1:
            x = x.reshape(-1, channels).mean(axis=1)
        loud = np.nonzero(np.abs(x) > 0.008)[0]
        if len(loud):
            pad = int(0.015 * SR)
            x = x[max(0, loud[0] - pad): min(len(x), loud[-1] + pad)]
        x = level_rms(x, VOICE_RMS_DB, VOICE_CEILING)
        if dsp.burst_db(x) > VOICE_BURST_DB:
            x = dsp.level(x, VOICE_BURST_DB, VOICE_CEILING)
        x = dsp.fade(x, 0.004, 0.03)
        with wave.open(str(path), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(SR)
            f.writeframes(dsp.to_int16(x).tobytes())
        print(f"  {path.relative_to(ROOT)}  {len(x) / SR:.2f}s  burst {dsp.burst_db(x):+.1f} dB")


def main() -> int:
    global USE_FOLEY
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default="", help="comma separated sfx names")
    ap.add_argument("--no-voice", action="store_true", help="skip the voice re-levelling pass")
    ap.add_argument("--no-reimport", action="store_true",
                    help="leave Godot's import cache alone (see tools/godot_reimport.py)")
    ap.add_argument("--palette", default="mix", choices=["mix", "synth"],
                    help="mix = recorded CC0 foley under the synth layers (default), "
                         "synth = the pre-foley palette, for A/B")
    args = ap.parse_args()

    USE_FOLEY = args.palette == "mix"
    if USE_FOLEY and not foley.available():
        print("! tools/foley is empty - run: python3 tools/foley.py --install")
        print("  rendering the synth-only palette instead")
        USE_FOLEY = False
    print(f"palette: {'foley + synth' if USE_FOLEY else 'synth only'}")

    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(SFX)
    if args.list:
        for n in names:
            print(n)
        return 0

    for name in names:
        data = SFX[name]()
        looping = name.endswith("_loop")
        # `balance()` already faded what it returns, so the edges are only faded
        # here for the hand-built sounds (the UI tones and the aura loop).
        mastered = name in CHARACTER
        write(SFX_DIR / f"{name}.wav", data, LEVELS.get(name, -16.0),
              fade_edges=not looping and not mastered, mastered=mastered)
    if not args.only and not args.no_voice:
        polish_voices()
    # Godot only re-imports in the editor, so without this the files just
    # written stay invisible to the game - see tools/godot_reimport.py.
    if not args.only and not args.no_reimport:
        godot_reimport.reimport()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
