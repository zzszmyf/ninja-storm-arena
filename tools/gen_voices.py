#!/usr/bin/env python3
"""Render the game's voice barks (attack shouts, hurt, KO, victory) with TTS.

A fighting game lives on its barks: a jab you never hear is a jab that never
lands. The first two passes over this file got the *shape* of a bark wrong in
ways that are easy to measure and were never measured:

  * Length. The Gemini voices read a four-syllable shout in 0.7-1.9 s. A bark
    that long no longer reads as one explosive sound - it reads as somebody
    calmly announcing the attack, and it walks straight over the next hit. A
    real fighting-game bark is 0.25-0.6 s; this file renders a take, measures
    it, and time-compresses it down to the shot's limit.
  * Pitch. Every voice on the Gemini endpoint measured a 270-330 Hz fundamental
    - an adult woman - and the old installer "fixed" that by resampling the
    take down seven semitones, which also slows it down 1.5x and moves every
    formant with it. That is the sound of a record played slow, not of a boy
    shouting. This file picks a voice that is already low and short (the xAI
    endpoint's male voices sit at 190-230 Hz), then corrects the few remaining
    takes toward a target fundamental by a couple of semitones, and finishes by
    compressing the duration back to the shot's limit *without* moving pitch
    again.
  * Whether it is Japanese at all. A voice that was not trained on Japanese
    will happily read kana as Latin letters. `--verify` sends every rendered
    take through a speech recogniser and reports what it hears.

    python3 tools/gen_voices.py --audition                 # compare voices
    python3 tools/gen_voices.py --audition --providers grok
    python3 tools/gen_voices.py --install --provider grok --voice rex
    python3 tools/gen_voices.py --install --verify
    python3 tools/gen_voices.py --check --verify           # audit what is installed

The audition board is written to docs/voice_audition.wav (plus .m4a when
afconvert is available) with the voice's own name spoken in front of each
block, so the file can be judged without a label sheet.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dsp  # noqa: E402
import godot_reimport  # noqa: E402
import zenmux  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tools" / "cache" / "voice_audition"
OUT_DIR = ROOT / "assets" / "audio" / "voice"
DOCS = ROOT / "docs"

API = "https://zenmux.ai/api/v1/audio/speech"
ASR_API = "https://zenmux.ai/api/v1/audio/transcriptions"
ASR_MODEL = "qwen/qwen3-asr-flash"
SOURCE_RATE = 24000

# Gemini understands a style instruction as a prefix on the text; xAI's voices
# take the line as-is.
STYLE = (
    "Deliver this as a young, hot-blooded anime boy in a fast, loud, punchy battle "
    "shout. Short, explosive and energetic, like a fighting-game voice bark. "
    "Do not read it calmly. Text: "
)

PROVIDERS = {
    "gemini": {
        "model": "google/gemini-3.1-flash-tts-preview",
        "voices": ["Enceladus", "Iapetus", "Charon", "Orus", "Zephyr", "Puck",
                   "Fenrir", "Sadaltager"],
        "prompt": lambda text: STYLE + text,
    },
    "grok": {
        "model": "x-ai/grok-voice-tts-1.0",
        "voices": ["rex", "orion", "sal", "eve", "leo", "ara", "luna"],
        "prompt": lambda text: text,
    },
}

# The installed voice, chosen by measurement rather than by name.
#
# Reading a full Japanese sentence back through the recogniser is what settles
# this: every Gemini voice speaks Japanese, but they all sit between 260 and
# 370 Hz - an adult woman - and pitch-shifting one of those into a teenage boy
# is what produced the "record played slow" barks of the last pass. The xAI
# voices are 130-270 Hz natively: `orion` reads the probe correctly at 136 Hz,
# which is the only combination on either endpoint that is both low and
# actually speaking Japanese.
DEFAULT_PROVIDER = "grok"
DEFAULT_VOICE = "orion"

# name -> (line, longest a take may be, target fundamental in Hz)
#
# The limits are the shot lengths the game actually plays into: a jab recovers
# in 0.14 s and a full combo in about 0.5 s, so a light bark has to be over
# before the next swing. A technique is the one place a longer shout belongs,
# because `chakra_charge` is 1.05 s long and the bark rides on top of it.
LINES = {
    "attack_light": ("とうっ！", 0.45, 150.0),
    "attack_heavy": ("どりゃっ！", 0.55, 145.0),
    "technique":    ("くらえっ！", 0.75, 150.0),
    "hurt":         ("ぐあっ！", 0.50, 140.0),
    "ko":           ("うわっ！", 0.60, 135.0),
    "win":          ("決まった！", 0.80, 145.0),
}

# A voice that cannot speak Japanese reads kana as Latin letters, and a
# 0.3 s bark is too short for a recogniser to catch it either way. The probe is
# therefore a real sentence: long enough to transcribe, and a sentence nobody
# would produce by accident.
PROBE_TEXT = "おれの忍術をくらえ！"

# How much of the correction may be done by resampling. The voices used here
# are picked so that little or none is needed; deeper than a couple of
# semitones and the take stops sounding like a person and starts sounding like
# a tape played slow.
MAX_SHIFT_ST = 2.0

# Installed barks are levelled on RMS with a cap on the loudest 20 ms, so a
# shout sits under the impact it accompanies. tools/build_audio.py re-levels
# them again after a render with the same numbers.
VOICE_RMS_DB = -15.5
VOICE_BURST_DB = -9.0
VOICE_CEILING = 0.90


# ------------------------------------------------------------------ network

def _post(url: str, payload: dict, timeout: float = 180.0) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer " + zenmux.api_key(),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def tts(text: str, voice: str, provider: str) -> bytes:
    cfg = PROVIDERS[provider]
    payload = _post(API, {
        "model": cfg["model"],
        "input": cfg["prompt"](text),
        "voice": voice,
        "response_format": "pcm",
    })
    if "error" in payload:
        raise RuntimeError(str(payload["error"])[:200])
    return base64.b64decode(payload["audio"])


def _wav_bytes(x: np.ndarray, rate: int = SOURCE_RATE) -> bytes:
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(dsp.to_int16(np.clip(x, -1.0, 1.0)).tobytes())
    return buf.getvalue()


def transcribe(x: np.ndarray, rate: int = SOURCE_RATE) -> str:
    """What a speech recogniser hears in `x`. Empty string if it is not speech.

    This is the check that catches a voice reading kana as Latin letters: the
    bark is only a Japanese battle shout if the words survive the round trip.
    """
    payload = _post(ASR_API, {
        "model": ASR_MODEL,
        "input_audio": {"data": base64.b64encode(_wav_bytes(x, rate)).decode(),
                        "format": "wav"},
    })
    if "error" in payload:
        raise RuntimeError(str(payload["error"])[:200])
    return str(payload.get("text", "")).strip()


# ------------------------------------------------------------------ analysis

def decode(pcm: bytes, rate: int = SOURCE_RATE) -> np.ndarray:
    x = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float64) / 32768.0
    if rate != dsp.SR:
        x = dsp.resample(x, dsp.SR / rate)
    return x


def trim(x: np.ndarray, thresh: float = 0.012, pad: float = 0.012) -> np.ndarray:
    """Drop the leading/trailing silence TTS likes to add."""
    if not len(x):
        return x
    loud = np.nonzero(np.abs(x) > thresh)[0]
    if not len(loud):
        return x
    n = int(pad * dsp.SR)
    return x[max(0, loud[0] - n) : min(len(x), loud[-1] + n)]


def median_f0(x: np.ndarray, rate: int = dsp.SR, fmin: float = 70.0,
              fmax: float = 420.0, thresh: float = 0.18) -> float:
    """Median fundamental over the voiced frames, in Hz (0.0 if unvoiced).

    A shout has a wildly moving fundamental - it is a glide, not a note - so
    the median over frames is the honest summary, and the frame is short enough
    (45 ms) that the glide is still inside it.

    This is YIN (cumulative-mean-normalised difference) rather than a plain
    autocorrelation peak, and that is not a detail. An autocorrelation lag
    search picks whichever period the waveform happens to fit, and a voice with
    strong harmonics fits two periods as well as one: the first version of this
    function read a synthesised 150 Hz vowel back as 300 Hz, and every voice it
    measured was therefore reported an octave high - which is how the installer
    ended up pitch-shifting barks that were already low enough.
    """
    window = int(0.045 * rate)
    hop = int(0.01 * rate)
    lo, hi = max(2, int(rate / fmax)), int(rate / fmin)
    hi = min(hi, window)
    if hi <= lo:
        return 0.0
    vals, weights = [], []
    for i in range(0, max(1, len(x) - window), hop):
        seg = x[i : i + window]
        level = float(np.sqrt(np.mean(np.square(seg))))
        if level < 0.02:
            continue
        seg = seg - seg.mean()
        diff = np.zeros(hi)
        for tau in range(1, hi):
            d = seg[: window - tau] - seg[tau:]
            diff[tau] = float(np.sum(d * d))
        cum = np.zeros(hi)
        run = 0.0
        for tau in range(1, hi):
            run += diff[tau]
            cum[tau] = diff[tau] * tau / max(run, 1e-12)
        tau = 0
        for t in range(lo, hi - 1):
            if cum[t] < thresh and cum[t] <= cum[t + 1]:
                tau = t
                break
        if not tau:
            t = int(np.argmin(cum[lo:hi])) + lo
            if cum[t] > 0.45:  # no periodicity worth reporting
                continue
            tau = t
        if 0 < tau < hi - 1:  # sub-sample the dip for a stable reading
            a, b, c = cum[tau - 1], cum[tau], cum[tau + 1]
            denom = a - 2.0 * b + c
            if abs(denom) > 1e-12:
                tau += float(np.clip(0.5 * (a - c) / denom, -1.0, 1.0))
        vals.append(rate / tau)
        weights.append(level)
    if not vals:
        return 0.0
    order = np.argsort(vals)
    vals = np.asarray(vals)[order]
    weights = np.asarray(weights)[order]
    return float(vals[int(np.searchsorted(np.cumsum(weights), weights.sum() / 2.0))])


def voiced_length(x: np.ndarray, thresh: float = 0.012) -> float:
    if not len(x):
        return 0.0
    loud = np.nonzero(np.abs(x) > thresh)[0]
    return (loud[-1] - loud[0]) / dsp.SR if len(loud) else 0.0


def shot_cut(x: np.ndarray, limit: float, thresh: float = 0.012) -> np.ndarray:
    """End a bark at the shot's length, with a fade, rather than stretching it.

    A bark that outlives its animation is worse than a bark that is cut off:
    the first walks over the next hit, the second just sounds clipped. Cutting
    also costs nothing in quality, where an overlap-add stretch on a voice
    leaves the comb-filtered buzz that the previous version of this file
    measured and then shipped anyway.
    """
    if limit <= 0.0 or not len(x):
        return x
    loud = np.nonzero(np.abs(x) > thresh)[0]
    if not len(loud):
        return x
    end = loud[0] + int((limit + 0.02) * dsp.SR)
    return x[:end].copy() if end < len(x) else x


def fit(x: np.ndarray, max_dur: float, target_f0: float) -> tuple[np.ndarray, float]:
    """Correct one take toward its shot: a small pitch nudge, then a tail cut.

    The loudest lever here is choosing the right voice in the first place. What
    is left over is corrected by resampling - which keeps the formants in
    proportion, because they are moved by the same ratio - and by cutting the
    take to length. Nothing in this path uses a time stretch: the barks are
    short and the words are the point, so intelligibility wins.
    """
    f0 = median_f0(x)
    shift = 0.0
    if f0 > 0.0 and target_f0 > 0.0 and f0 > target_f0 * 1.12:
        want = 12.0 * np.log2(target_f0 / f0)
        shift = float(np.clip(want, -MAX_SHIFT_ST, 0.0))
    if shift < -0.1:
        x = dsp.pitch_shift(x, shift)
    return dsp.fade(shot_cut(x, max_dur), 0.004, 0.03), shift


def polish(x: np.ndarray) -> np.ndarray:
    """Match the level the runtime expects: RMS target, burst cap, faded edges."""
    rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    if rms > 1e-9:
        x = x * (10.0 ** ((VOICE_RMS_DB - 20.0 * np.log10(rms)) / 20.0))
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > VOICE_CEILING:
        x = x * (VOICE_CEILING / peak)
    if dsp.burst_db(x) > VOICE_BURST_DB:
        x = dsp.level(x, VOICE_BURST_DB, VOICE_CEILING)
    return dsp.fade(x, 0.004, 0.03)


def write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(dsp.SR)
        f.writeframes(dsp.to_int16(x).tobytes())


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as f:
        channels, rate = f.getnchannels(), f.getframerate()
        raw = f.readframes(f.getnframes())
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    if rate != dsp.SR:
        x = dsp.resample(x, dsp.SR / rate)
    return x


# ----------------------------------------------------------------- commands

def render_take(name: str, provider: str, voice: str) -> tuple[np.ndarray, float, float]:
    """One line as it would be installed: (take, raw take length, pitch shift)."""
    text, max_dur, target_f0 = LINES[name]
    raw = trim(decode(tts(text, voice, provider)))
    raw_dur = voiced_length(raw)
    clip, shift = fit(raw, max_dur, target_f0)
    return clip, raw_dur, shift


def cmd_install(args) -> int:
    provider, voice = args.provider, args.voice
    names = [n.strip() for n in args.lines.split(",") if n.strip()] or list(LINES)
    print(f"installing voice barks: provider={provider} voice={voice}")
    if args.verify:
        print("  japanese probe:", probe_japanese(provider, voice))
    print(f"  {'line':14s} {'raw':>5s} {'shift':>6s} {'F0':>6s} {'burst':>7s}  heard as")
    bad = 0
    for name in names:
        try:
            clip, raw_dur, shift = render_take(name, provider, voice)
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
            print(f"  {name:14s} FAILED {exc}")
            bad += 1
            continue
        heard = ""
        if args.verify:
            try:
                heard = transcribe(clip)
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
                heard = f"(verify failed: {exc})"
        x = polish(clip)
        write_wav(OUT_DIR / f"{name}.wav", x)
        print(f"  {name:14s} {raw_dur:5.2f} {shift:+6.2f} {median_f0(x):6.1f} "
              f"{dsp.burst_db(x):+6.1f}  {heard}")
    if bad:
        print(f"{bad} line(s) failed")
        return 1
    # A rewritten take is invisible to a game launched from the command line
    # until Godot re-imports it - see tools/godot_reimport.py.
    if not args.no_reimport:
        godot_reimport.reimport()
    return 0


def cmd_audition(args) -> int:
    providers = [p.strip() for p in args.providers.split(",") if p.strip()] or list(PROVIDERS)
    names = [n.strip() for n in args.lines.split(",") if n.strip()] or list(LINES)
    CACHE.mkdir(parents=True, exist_ok=True)
    board: list[np.ndarray] = []
    print(f"  {'provider/voice':24s} {'line':14s} {'take':>5s} {'F0':>6s}  heard as")
    for provider in providers:
        for voice in PROVIDERS[provider]["voices"]:
            # Say the voice's own name first, so the board needs no label sheet.
            try:
                label = trim(decode(tts(f"{voice}。", voice, provider)))
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
                print(f"  {provider}/{voice:20s} label failed: {exc}")
                continue
            board += [label, dsp.silence(0.30)]
            for name in names:
                try:
                    clip, _, _ = render_take(name, provider, voice)
                except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
                    print(f"  {provider}/{voice:20s} {name:14s} failed: {exc}")
                    continue
                heard = ""
                if args.verify:
                    try:
                        heard = transcribe(clip)
                    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
                        heard = f"(verify failed: {exc})"
                print(f"  {provider + '/' + voice:24s} {name:14s} "
                      f"{voiced_length(clip):5.2f} {median_f0(clip):6.1f}  {heard}")
                board += [clip, dsp.silence(0.35)]
            board.append(dsp.silence(0.6))
    if not board:
        print("nothing rendered")
        return 1
    dest = DOCS / "voice_audition.wav"
    write_wav(dest, dsp.normalise(np.concatenate(board), 0.85))
    print("  ->", dest.relative_to(ROOT))
    _to_m4a(dest)
    return 0


def cmd_check(args) -> int:
    """Audit the installed barks against this file's brief."""
    names = [n.strip() for n in args.lines.split(",") if n.strip()] or list(LINES)
    print(f"  {'line':14s} {'take':>5s} {'limit':>6s} {'F0':>6s} {'target':>7s}  heard as")
    bad = 0
    for name in names:
        path = OUT_DIR / f"{name}.wav"
        if not path.exists():
            print(f"  {name:14s} MISSING")
            bad += 1
            continue
        x = load_wav(path)
        _, limit, target = LINES[name]
        dur, f0 = voiced_length(x), median_f0(x)
        flag = ""
        if dur > limit + 0.01:
            flag += f"  <- over {limit:.2f}s"
            bad += 1
        if f0 and f0 > target * 1.25:
            flag += f"  <- high (target {target:.0f} Hz)"
            bad += 1
        heard = transcribe(x) if args.verify else ""
        print(f"  {name:14s} {dur:5.2f} {limit:6.2f} {f0:6.1f} {target:7.1f}  {heard}{flag}")
    if bad:
        print(f"VOICE CHECK: {bad} problem(s)")
        return 1
    print("VOICE CHECK OK")
    return 0


def probe_japanese(provider: str, voice: str) -> str:
    """Read a full sentence and report what the recogniser heard."""
    try:
        take = trim(decode(tts(PROBE_TEXT, voice, provider)))
        return f"'{transcribe(take)}'"
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        return f"(failed: {exc})"


def _to_m4a(wav_path: Path) -> None:
    """Compress a board for quick listening, if the platform tool exists."""
    m4a = wav_path.with_suffix(".m4a")
    try:
        subprocess.run(
            ["afconvert", "-f", "m4af", "-d", "aac", "-b", "128000",
             str(wav_path), str(m4a)],
            check=True, capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audition", action="store_true", help="compare voices on one board")
    ap.add_argument("--install", action="store_true", help="install a voice into the game")
    ap.add_argument("--check", action="store_true", help="audit the installed barks")
    ap.add_argument("--provider", default=DEFAULT_PROVIDER, choices=sorted(PROVIDERS))
    ap.add_argument("--providers", default="", help="comma separated, for --audition")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--lines", default="", help="comma separated line names")
    ap.add_argument("--verify", action="store_true",
                    help="transcribe every take and report what it sounds like")
    ap.add_argument("--no-reimport", action="store_true",
                    help="leave Godot's import cache alone (see tools/godot_reimport.py)")
    args = ap.parse_args()
    if args.check:
        return cmd_check(args)
    if args.audition:
        return cmd_audition(args)
    if args.install:
        return cmd_install(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
