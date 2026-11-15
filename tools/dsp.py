"""Tiny synthesizer toolkit used to render the game's sound effects.

Everything here works on float32 numpy buffers in the -1..1 range, at a fixed
sample rate. The building blocks are deliberately simple: sweeps, noise, a few
filters, envelopes and a cheap reverb. That is enough to build convincing
anime-style impacts, swings and chakra blasts without shipping any sampled
audio or depending on a licensed sound library.
"""

from __future__ import annotations

import numpy as np

SR = 44100


# ------------------------------------------------------------------ sources

def t_axis(dur: float, sr: int = SR) -> np.ndarray:
    return np.arange(int(dur * sr), dtype=np.float64) / sr


def silence(dur: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(dur * sr), dtype=np.float64)


def sine(freq: float, dur: float, phase: float = 0.0, sr: int = SR) -> np.ndarray:
    t = t_axis(dur, sr)
    return np.sin(2 * np.pi * freq * t + phase)


def noise(dur: float, seed: int = 0, sr: int = SR) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 1.0, int(dur * sr))


def sweep(f0: float, f1: float, dur: float, curve: float = 1.0, sr: int = SR) -> np.ndarray:
    """Sine whose frequency glides from f0 to f1 (curve > 1 = slower at first)."""
    n = int(dur * sr)
    t = np.linspace(0.0, 1.0, n, endpoint=False)
    freqs = f0 + (f1 - f0) * (t ** curve)
    phase = np.cumsum(2 * np.pi * freqs / sr)
    return np.sin(phase)


def pulse(freq: float, dur: float, duty: float = 0.5, sr: int = SR) -> np.ndarray:
    t = t_axis(dur, sr)
    return np.where((t * freq) % 1.0 < duty, 1.0, -1.0)


def karplus(freq: float, dur: float, damp: float = 0.5, seed: int = 1, sr: int = SR) -> np.ndarray:
    """Plucked-string synthesis, used for the koto/shamisen in the music."""
    n = int(dur * sr)
    length = max(2, int(sr / max(20.0, freq)))
    buf = np.random.default_rng(seed).normal(0.0, 1.0, length)
    out = np.zeros(n)
    idx = 0
    for i in range(n):
        out[i] = buf[idx]
        nxt = (idx + 1) % length
        buf[idx] = (buf[idx] + buf[nxt]) * 0.5 * damp
        idx = nxt
    return out


# ------------------------------------------------------------------ shaping

def env_ad(dur: float, attack: float, decay: float, curve: float = 2.4, sr: int = SR) -> np.ndarray:
    """Attack / decay envelope, normalised to the buffer length."""
    n = int(dur * sr)
    a = max(1, int(attack * sr))
    env = np.ones(n)
    env[:a] = np.linspace(0.0, 1.0, a) ** 0.6
    tail = np.linspace(0.0, 1.0, n - a, endpoint=False)
    env[a:] = np.exp(-tail * decay * curve)
    return env


def env_swell(dur: float, power: float = 2.0, sr: int = SR) -> np.ndarray:
    n = int(dur * sr)
    t = np.linspace(0.0, 1.0, n)
    return (t ** power) * (1.0 - t) ** 0.35 / max(1e-6, (np.max((t ** power) * (1.0 - t) ** 0.35)))


def env_adsr(dur: float, a: float, d: float, s: float, r: float, sr: int = SR) -> np.ndarray:
    n = int(dur * sr)
    na, nd, nr = int(a * sr), int(d * sr), int(r * sr)
    ns = max(0, n - na - nd - nr)
    parts = [
        np.linspace(0.0, 1.0, max(1, na)),
        np.linspace(1.0, s, max(1, nd)),
        np.full(max(1, ns), s),
        np.linspace(s, 0.0, max(1, nr)),
    ]
    env = np.concatenate(parts)[:n]
    return np.pad(env, (0, max(0, n - len(env))))


def fade(x: np.ndarray, fade_in: float = 0.002, fade_out: float = 0.01, sr: int = SR) -> np.ndarray:
    n = len(x)
    a = min(n, max(0, int(fade_in * sr)))
    b = min(n, max(0, int(fade_out * sr)))
    if a:
        x[:a] *= np.linspace(0.0, 1.0, a)
    if b:
        x[-b:] *= np.linspace(1.0, 0.0, b)
    return x


def saturate(x: np.ndarray, drive: float = 1.6) -> np.ndarray:
    return np.tanh(x * drive) / np.tanh(drive)


# ------------------------------------------------------------- bus glue

def _block_max(x: np.ndarray, w: int) -> np.ndarray:
    """Sliding maximum over `w` samples, in O(n) and without Python loops.

    A peak-hold envelope is a compressor's detector. Doing it with a one-pole
    recursion costs a Python iteration per sample, and build_audio.py evaluates
    a candidate mix thousands of times per sound; the prefix/suffix-maxima
    decomposition below gives the same answer vectorised.
    """
    n = len(x)
    if n == 0 or w <= 1:
        return x.copy()
    pad = (-n) % w
    if pad:
        x = np.concatenate([x, np.zeros(pad)])
    blocks = x.reshape(-1, w)
    pre = np.maximum.accumulate(blocks, axis=1).ravel()
    suf = np.maximum.accumulate(blocks[:, ::-1], axis=1)[:, ::-1].ravel()
    # Window ending at i is [i-w+1, i]: its left half lives in `suf`, its right
    # half in `pre`. Before the first full window, `pre` alone is the answer.
    left = np.concatenate([np.full(w - 1, -np.inf), suf[: len(suf) - (w - 1)]])
    return np.maximum(left, pre)[:n]


def _sliding_mean(x: np.ndarray, w: int) -> np.ndarray:
    """Box filter of width `w` over a 1-D array, edges included."""
    n = len(x)
    if n == 0 or w <= 1:
        return x.copy()
    c = np.concatenate([[0.0], np.cumsum(x)])
    idx = np.arange(n)
    lo = np.maximum(idx - w + 1, 0)
    hi = idx + 1
    return (c[hi] - c[lo]) / (hi - lo)


def glue(x: np.ndarray, window: float = 0.0015, thr: float = 1.6,
         ratio: float = 3.0, sr: int = SR) -> np.ndarray:
    """Clamp the leading spike so every layer of a hit shares one envelope.

    The palette is built by stacking a bright crack, a mid smack and a low body,
    each with its own decay, and a listener reports what that mathematically is:
    "a whip crack, a thwack and a thump that do not meld into one impact". A bus
    compressor is the standard answer - one gain envelope driven by the sum, so
    the layers rise and fall together - but the settings decide whether it helps.
    A slow attack ducks the body *after* the crack and makes the sound thinner;
    this one clamps the first ~1.5 ms at 3:1, so the spike that reads as a menu
    click comes down and the flesh under it comes up.

    `x` is RMS-normalised by the caller (see build_audio._render), so `thr` is
    in multiples of the sound's own RMS rather than an absolute level: 1.6 means
    "only the top ~4 dB above average is compressed", which leaves a tailed boom
    almost untouched while still working on a 150 ms jab.
    """
    if len(x) == 0 or ratio <= 1.0 or thr <= 0.0:
        return x
    w = max(2, int(window * sr))
    env = _block_max(np.abs(x), w)
    gain = np.ones_like(env)
    over = env > thr
    if np.any(over):
        gain[over] = (thr / env[over]) ** (1.0 - 1.0 / ratio)
    # Step changes in gain would zipper on the crack; one box filter over the
    # gain, as wide as the detector, is enough to make it inaudible.
    return x * _sliding_mean(gain, w)


def normalise(x: np.ndarray, peak: float = 0.95) -> np.ndarray:
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return x * (peak / m) if m > 1e-9 else x


def rms_db(x: np.ndarray) -> float:
    """Loudness proxy: RMS expressed in dBFS."""
    if not len(x):
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return 20.0 * np.log10(max(rms, 1e-6))


def level(x: np.ndarray, target_db: float, ceiling: float = 0.95) -> np.ndarray:
    """Scale a buffer so it sits at a target RMS, then keep it under a peak.

    Matching RMS across a palette is what stops a light jab from vanishing
    under a finisher boom: peak normalisation alone leaves short transients
    far quieter than long, dense sounds.
    """
    if not len(x):
        return x
    x = x * (10.0 ** ((target_db - burst_db(x)) / 20.0))
    m = float(np.max(np.abs(x)))
    if m > ceiling:
        x = x * (ceiling / m)
    return x


def burst_db(x: np.ndarray, win: float = 0.02, sr: int = SR) -> float:
    """Loudness of the loudest short window, in dBFS.

    Overall RMS is a bad loudness proxy for sound effects: a 0.2 s jab and a
    2 s gong can share a peak and an RMS while feeling wildly different. The
    loudest 20 ms window tracks what the ear actually reacts to, so levelling
    on it keeps short impacts and long tails in the same perceived ballpark.
    """
    if not len(x):
        return -120.0
    n = max(1, min(len(x), int(win * sr)))
    power = np.square(x, dtype=np.float64)
    cum = np.concatenate(([0.0], np.cumsum(power)))
    means = (cum[n:] - cum[:-n]) / n
    if not len(means):
        means = power
    return 10.0 * np.log10(max(float(np.max(means)), 1e-12))


# ------------------------------------------------------------------ filters

def onepole_lp(x: np.ndarray, cutoff: np.ndarray | float, sr: int = SR) -> np.ndarray:
    """One-pole low pass; `cutoff` may be an array to sweep the filter."""
    cutoff = np.full(len(x), cutoff, dtype=np.float64) if np.isscalar(cutoff) else np.asarray(cutoff, dtype=np.float64)
    alpha = 1.0 - np.exp(-2.0 * np.pi * np.clip(cutoff, 10.0, sr * 0.49) / sr)
    out = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += alpha[i] * (x[i] - acc)
        out[i] = acc
    return out


def onepole_hp(x: np.ndarray, cutoff: np.ndarray | float, sr: int = SR) -> np.ndarray:
    lo = onepole_lp(x, cutoff, sr)
    return x - lo


def _biquad(x: np.ndarray, b: tuple, a: tuple) -> np.ndarray:
    b0, b1, b2 = b
    a0, a1, a2 = a
    y = np.empty_like(x)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(len(x)):
        v = x[i]
        out = (b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0
        y[i] = out
        x2, x1 = x1, v
        y2, y1 = y1, out
    return y


def bandpass(x: np.ndarray, centre: float, q: float = 1.0, sr: int = SR) -> np.ndarray:
    w0 = 2.0 * np.pi * centre / sr
    alpha = np.sin(w0) / (2.0 * q)
    return _biquad(x, (alpha, 0.0, -alpha), (1.0 + alpha, -2.0 * np.cos(w0), 1.0 - alpha))


def resonator(x: np.ndarray, freq: float, decay: float, sr: int = SR) -> np.ndarray:
    """Ring a decaying sine out of a short excitation - metallic clangs."""
    r = np.exp(-1.0 / (max(0.001, decay) * sr))
    w0 = 2.0 * np.pi * freq / sr
    b = (1.0 - r, 0.0, 0.0)
    a = (1.0, -2.0 * r * np.cos(w0), r * r)
    return _biquad(x, b, a)


def modal(x: np.ndarray, freq: float, decay: float, sr: int = SR) -> np.ndarray:
    """One ringing mode of a struck object, excited by `x`.

    This is the sibling of `resonator`, and the difference matters. `resonator`
    is a unit-peak-gain filter: fed a short strike, its output level collapses
    as the ring gets longer (energy scales with `(1-r)/(1+r)`), so a mode that
    rings for two seconds comes out roughly a thousand times quieter than one
    that rings for a millisecond. Any bell or gong built on it is a click with
    no tone.

    A modal partial is defined by its impulse response instead - the strike
    sets the level, the decay only sets how long it rings - which is how struck
    metal actually behaves. Note the peak of `h[n] = r^n sin((n+1)w0)/sin(w0)`
    is about 1, so partials can be summed without renormalising per decay.
    """
    r = np.exp(-1.0 / (max(0.001, decay) * sr))
    w0 = 2.0 * np.pi * freq / sr
    return _biquad(x, (1.0, 0.0, 0.0), (1.0, -2.0 * r * np.cos(w0), r * r))


def reson_sweep(x: np.ndarray, f0: float, f1: float, q: float = 1.6, curve: float = 1.0,
                sr: int = SR) -> np.ndarray:
    """Resonant band pass whose centre frequency glides from f0 to f1.

    This is the difference between air moving and air hissing. A fixed filter
    turns noise into flat "shhh"; sweeping a resonance through the spectrum is
    what the ear reads as a limb whipping past it - the "hyu" of a punch that
    missed, or of a body lifting off the ground.

    Implemented with a Chamberlin state-variable filter: cheap, stable, and it
    has band-pass output available per sample, which is what a sweep needs.
    """
    n = len(x)
    if n == 0:
        return x.copy()
    t = np.linspace(0.0, 1.0, n) ** curve
    freq = f0 + (f1 - f0) * t
    # g = 2*sin(pi*f/sr) is the stability limit of this topology; keep it well
    # inside that or the filter blows up on the top of a fast sweep.
    g = np.clip(2.0 * np.sin(np.pi * np.clip(freq, 20.0, sr * 0.45) / sr), 0.0, 0.85)
    damp = 1.0 / max(0.5, q)
    low = 0.0
    band = 0.0
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        high = x[i] - low - damp * band
        band += g[i] * high
        low += g[i] * band
        out[i] = band
    return out


# ------------------------------------------------------------------ effects

def reverb_wet(x: np.ndarray, decay: float = 0.45, sr: int = SR) -> np.ndarray:
    """The tail tap of the reverb: a few combs plus a low pass. Linear in `x`."""
    if decay <= 0.0:
        return np.zeros_like(x)
    wet = np.zeros_like(x)
    for delay_ms, gain in ((29.7, 0.42), (37.1, 0.36), (41.1, 0.32), (43.7, 0.28)):
        d = max(1, int(delay_ms * 1e-3 * sr))
        g = gain * decay
        buf = np.zeros(len(x) + d)
        buf[: len(x)] = x
        for i in range(d, len(buf)):
            buf[i] += buf[i - d] * g
        wet += buf[: len(x)]
    return onepole_lp(wet, 4200.0, sr)


def reverb_lin(x: np.ndarray, room: float = 0.35, decay: float = 0.45,
               sr: int = SR) -> np.ndarray:
    """Same reverb, but strictly linear in `x`.

    `reverb` normalises the wet signal, which is what the music wants but makes
    the effect depend on the level of its input - so it cannot be applied to
    each layer of an impact before the layers are mixed. Sound effects use this
    version, which lets tools/build_audio.py pre-render a room onto every layer
    once and then solve the mix cheaply.
    """
    if decay <= 0.0 or room <= 0.0:
        return x
    return (1.0 - room) * x + room * reverb_wet(x, decay, sr)


def reverb(x: np.ndarray, room: float = 0.35, decay: float = 0.45, sr: int = SR) -> np.ndarray:
    """Cheap Schroeder-ish reverb: a few combs plus a low pass on the tail."""
    if decay <= 0.0:
        return x
    return (1.0 - room) * x + room * normalise(reverb_wet(x, decay, sr), 1.0)


def mix(*layers: np.ndarray) -> np.ndarray:
    n = max(len(l) for l in layers)
    out = np.zeros(n)
    for l in layers:
        out[: len(l)] += l[:n]
    return out


def place(dest: np.ndarray, src: np.ndarray, at: float, gain: float = 1.0, sr: int = SR) -> np.ndarray:
    i = int(at * sr)
    end = min(len(dest), i + len(src))
    if end <= i:
        return dest
    dest[i:end] += src[: end - i] * gain
    return dest


def place_wrap(dest: np.ndarray, src: np.ndarray, at: float, gain: float = 1.0, sr: int = SR) -> np.ndarray:
    """Like `place`, but the tail wraps around to the head of the buffer.

    Music beds are rendered as a fixed-length loop, so a reverb tail or a
    ringing hit that runs past the final beat has to land back at the top
    instead of being chopped off - otherwise every loop point clicks.
    """
    n = len(dest)
    if n == 0 or not len(src):
        return dest
    i = int(at * sr) % n
    head = min(n - i, len(src))
    dest[i : i + head] += src[:head] * gain
    rest = len(src) - head
    if rest > 0:
        dest[:rest] += src[head:] * gain
    return dest


def loopify(x: np.ndarray, cross: float = 0.25, sr: int = SR) -> np.ndarray:
    """Cross-fade the tail into the head so the buffer loops without a click."""
    n = int(cross * sr)
    if n * 2 >= len(x):
        return x
    head = x[:n].copy()
    tail = x[-n:].copy()
    ramp = np.linspace(0.0, 1.0, n)
    x = x[:-n]
    x[:n] = tail * (1.0 - ramp) + head * ramp
    return x


def resample(x: np.ndarray, ratio: float) -> np.ndarray:
    """Resample by linear interpolation (ratio > 1 = longer / lower)."""
    n = int(len(x) * ratio)
    if n < 2:
        return x.copy()
    idx = np.linspace(0.0, len(x) - 1.0, n)
    return np.interp(idx, np.arange(len(x)), x)


def time_stretch(x: np.ndarray, target_len: int, frame: int = 1024, sr: int = SR) -> np.ndarray:
    """Overlap-add time stretch that keeps the pitch, used by `pitch_shift`."""
    if target_len <= 0 or len(x) < frame * 2:
        return resample(x, max(1e-3, target_len / max(1, len(x))))
    hop_analysis = frame // 4
    ratio = target_len / len(x)
    hop_synthesis = max(1, int(hop_analysis * ratio))
    window = np.hanning(frame)
    out = np.zeros(target_len + frame)
    weight = np.zeros_like(out)
    src = 0
    dst = 0
    while src + frame < len(x) and dst + frame < len(out):
        out[dst : dst + frame] += x[src : src + frame] * window
        weight[dst : dst + frame] += window
        src += hop_analysis
        dst += hop_synthesis
    nz = weight > 1e-6
    out[nz] /= weight[nz]
    return out[:target_len]


def pitch_shift(x: np.ndarray, semitones: float, keep_duration: bool = False, sr: int = SR) -> np.ndarray:
    """Shift pitch by resampling.

    Resampling is the clean way to deepen a voice - it moves pitch and duration
    together, so a bark comes out a little slower and heavier, which suits an
    attack shout. The TTS voices available are all fairly high, so a handful of
    semitones down is what turns one into a teenage boy.

    `keep_duration=True` staples the length back with an overlap-add stretch,
    which keeps the timing but adds a comb-filtered buzz, so it is off by
    default.
    """
    if abs(semitones) < 0.01 or not len(x):
        return x
    ratio = 2.0 ** (semitones / 12.0)
    shifted = resample(x, 1.0 / ratio)
    if keep_duration:
        shifted = time_stretch(shifted, len(x), sr=sr)
    return shifted


def to_int16(x: np.ndarray) -> np.ndarray:
    return np.clip(x * 32767.0, -32768, 32767).astype("<i2")
