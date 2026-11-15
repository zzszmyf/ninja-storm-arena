#!/usr/bin/env python3
"""Give the audio pipeline a pair of ears.

Nobody in this loop can listen to the rendered wav files, so every judgement
about the palette is made from spectra - and a spectrum can say "this is bright
and punchy" while the sound itself reads as an item pickup. This tool ships a
file to a model that *hears* it and asks for a sound designer's second opinion,
which is then used to decide what to re-render.

    python3 tools/audio_ears.py --calibrate          # is the model hearing?
    python3 tools/audio_ears.py                      # whole palette
    python3 tools/audio_ears.py --only hit_light,block
    python3 tools/audio_ears.py --group music
    python3 tools/audio_ears.py --out docs/audio_ears_sfx.md

Results are cached per file (keyed by a hash of the samples) under
tools/cache/ears/ so re-running is free until the sound changes.

Two things had to be settled before any of this was worth reading, and both
were got wrong the first time round:

  * The model has to hear. The first version of this file used Xiaomi MiMo-V2.5
    because it was the only model that answered a two-tone pitch test. That test
    is far too easy: shown four clips and asked which was the punch, the bell,
    the click and the tone, MiMo scored 0/4, and handed a *recording* of a real
    punch it reported "a pure mono oscillator" at 1/10. Every score in the first
    revision of docs/audio_ears_sfx.md came from that. `--calibrate` now runs
    the identification test and refuses to grade the palette with a model that
    cannot pass it.
  * The prompt has to not lead. The first brief announced that the palette was
    "synthesised from scratch" and asked for "the artefacts that reveal it was
    synthesised", then asked how close the file came to a library recording. A
    model given that brief will find synthesis artefacts in a field recording,
    and it did. The brief below states the intended event - a sound designer
    needs the brief - but asks what the clip reads as *first*, and asks for a
    rating against that event rather than against an unstated ideal.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import godot_reimport  # noqa: E402  (path fix only)
import zenmux  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SFX_DIR = ROOT / "assets" / "audio" / "sfx"
VOICE_DIR = ROOT / "assets" / "audio" / "voice"
MUSIC_DIR = ROOT / "assets" / "audio" / "music"
CACHE = ROOT / "tools" / "cache" / "ears"

# Which model does the hearing. Gemini 2.5 Pro is the one that passes
# `--calibrate`: handed four clips and asked to name them, it gets the punch,
# the bell, the click and the tone right, and its descriptions of this palette
# are specific enough to act on ("a sharp metallic strike with a shimmering
# tonal decay ... reads as item acquired" is a real bug report about a hit).
# Swapping this line means re-running `--calibrate` before believing anything
# it says; see the module docstring for what MiMo-V2.5 did with the same job.
API = "https://zenmux.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-pro"

VOICE_EVENTS = {
    "attack_light": "a light attack shout",
    "attack_heavy": "a heavy attack shout",
    "hurt": "taking a hit",
    "technique": "calling out a ninja technique",
    "ko": "being knocked out",
    "win": "winning the match",
}

MUSIC_EVENTS = {
    "battle_loop": "the loop that plays during a fight",
    "result_sting": "the sting that plays on the result screen",
}

# What each effect is supposed to be in the game. The brief gives the model the
# intended event and nothing else: no adjective from the render script ("bright",
# "weighty"), because a prompt that describes the sound gets the description
# back as a review. `tools/build_audio.py --list` and the docstrings there are
# the other half of this table and must stay in step with it - a brief that says
# "metal clang" about a file the renderer built as a taiko drum is a review of
# the wrong sound, and the fix it suggests will be wrong too.
SFX_EVENTS = {
    "hit_light": "a light jab landing on an opponent",
    "hit_medium": "a solid mid-strength punch connecting",
    "hit_heavy": "a heavy finishing blow landing",
    "launcher": "the third hit of a combo, blowing the opponent away",
    "whoosh_light": "a quick punch swinging through empty air",
    "whoosh_heavy": "a wide heavy swing through empty air",
    "dash": "a fighter dashing quickly through the air",
    "poof": "a puff of smoke from a substitution or clone technique",
    "block": "a kunai deflecting another kunai as a guard holds",
    "chakra_charge": "a ninja gathering chakra energy, rising in intensity",
    "chakra_shoot": "firing a ball of chakra energy out of the hand",
    "chakra_hit": "a chakra energy ball detonating on an opponent",
    "jump": "a fighter jumping off the ground",
    "land": "boots hitting the ground on landing",
    "ko": "the knockout blow that ends the match",
    "round_start": "the drum and bell that open a round",
    "time_up": "the bell that ends the round on the timer",
    "ui_move": "a menu cursor moving",
    "ui_confirm": "a menu option being confirmed",
    "aura_loop": "the looping aura of energy around a powered-up fighter",
}


def brief(kind: str, event: str) -> str:
    """The prompt for one file.

    Deliberately open and ordered: what the file sounds like, and what it reads
    as, come before the intended event, so the guess is not just the brief
    echoed back. The rating afterwards is against that event, which is the only
    question the renderer can act on - "how good is this sound in the abstract"
    has no answer, and a model asked to hunt for synthesis artefacts will find
    them in a field recording.
    """
    subject = {"sfx": "sound effect", "voice": "voice recording",
               "music": "piece of music"}[kind]
    return (
        f"You are a sound designer who worked on 2D anime fighting games in "
        f"the GBA and DS era. Listen to the attached {subject} and answer in "
        f"exactly this shape, no preamble.\n\n"
        "SOUND: what you actually hear, in plain words, as if this were a "
        "phone call with another sound designer. One or two sentences.\n"
        "READS AS: the single game event this clip would fit best if you found "
        "it unlabelled in a folder. Name one event, or say \"nothing\".\n"
        f"HITS: this clip is meant to be {event}. Rate how well it lands that "
        "as \"<score>/10 - <why>\".\n"
        "OFF: what gives away that it is not a finished library effect - "
        "timbre, decay, layers, stereo, pitch movement, level. If it already "
        "sounds finished, say so.\n"
        "FIX: the single change that would most improve it. One sentence.\n\n"
        "Keep the whole answer under 150 words. Do not pad it, and do not "
        "guess at how the file was made - describe what you hear."
    )


def wav_bytes(path: Path, max_seconds: float = 12.0) -> tuple[bytes, str]:
    """Read a wav, downmix to mono, and return (raw bytes, format)."""
    with wave.open(str(path), "rb") as f:
        rate = f.getframerate()
        channels = f.getnchannels()
        n = min(f.getnframes(), int(max_seconds * rate))
        raw = f.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    # 44.1k mono wav is a big payload for a chat request; the palette lives
    # below 8 kHz on purpose, so halving the rate costs nothing audible and
    # keeps every file well inside the request limit.
    #
    # The first version of this did `x[::2]`, which is not a sample rate
    # conversion: taking every other sample folds everything from 11 to 22 kHz
    # back down into the audible band, and a recorded punch - which has real
    # energy up there - arrives at the model as a fizzy metallic buzz. Filter
    # first, then drop the samples.
    if rate > 22050:
        x = _decimate(x, 2) if rate == 44100 else x
        rate = 22050
    pcm = np.clip(x * 32767.0, -32768, 32767).astype("<i2").tobytes()
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)
    return buf.getvalue(), "wav"


def _decimate(x: np.ndarray, factor: int) -> np.ndarray:
    """Half-band filter then drop samples, so the model hears the real sound."""
    taps = 63
    n = np.arange(taps) - (taps - 1) / 2.0
    h = np.sinc(n / factor) * np.hamming(taps)
    h /= h.sum()
    return np.convolve(x, h, mode="same")[::factor]


def digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:16]


def critique(name: str, data: bytes, fmt: str, prompt: str) -> str:
    body = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio", "input_audio": {
                    "data": base64.b64encode(data).decode(), "format": fmt}},
            ],
        }],
        "max_tokens": 700,
    }
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + zenmux.api_key()})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.load(r)
            return out["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code in zenmux.RETRYABLE and attempt < 2:
                continue
            return f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
    return "unreachable"


def audit(path: Path, prompt: str, force: bool = False) -> str:
    data, fmt = wav_bytes(path)
    CACHE.mkdir(parents=True, exist_ok=True)
    # The model is part of the key: a critique is only meaningful from the
    # model that earned its ears, and Gemini's hallucinated ones had to be
    # thrown away by hand once already.
    #
    # The prompt is part of it too. Rewriting the brief without changing the
    # key is how a report ends up full of answers to a question that is no
    # longer being asked - the old cache would still be the first thing read.
    tag = MODEL.split("/")[-1]
    cache_file = CACHE / f"{path.stem}_{tag}_{digest(data)}_{digest(prompt.encode())}.txt"
    if cache_file.exists() and not force:
        return cache_file.read_text()
    text = critique(path.stem, data, fmt, prompt)
    cache_file.write_text(text)
    return text


# ----------------------------------------------------------------- calibrating

# The probes: three sounds whose identity is not a matter of taste, plus a pair
# of tones. `key` are the words a model that hears the clip will use somewhere
# in one line about it - not a strict vocabulary, but enough that a model
# answering from the text of the prompt alone cannot pass by accident.
PROBES: list[tuple[str, str, tuple[str, ...]]] = [
    ("a recording of a fist hitting a body", "foley/punch_heavy_0.wav",
     ("punch", "thud", "impact", "fist", "hit", "body", "smash", "strike")),
    ("a recording of a large metal bell being struck", "foley/bell_heavy_0.wav",
     ("bell", "ring", "chime", "metal", "clang", "gong")),
    ("a steady 150 Hz sine tone", "<tone:150>",
     ("low", "bass", "hum", "tone", "sine", "drone")),
    ("a steady 5 kHz sine tone", "<tone:5000>",
     ("high", "tone", "beep", "sine", "pitch", "whistle")),
]

PROBE_PROMPT = (
    "Listen to the attached audio clip. In one short line, say what you hear "
    "and whether it is a recording of something physical or an electronic tone."
)


def _probe_clip(spec: str) -> tuple[bytes, str]:
    """A calibration clip: either a file in tools/foley, or a synthetic tone."""
    if spec.startswith("<tone:"):
        freq = float(spec[6:-1])
        t = np.arange(int(0.6 * 44100)) / 44100.0
        x = 0.6 * np.sin(2 * np.pi * freq * t)
        tmp = CACHE / "probe"
        tmp.mkdir(parents=True, exist_ok=True)
        path = tmp / f"tone{int(freq)}.wav"
        import io

        pcm = (x * 32767).astype("<i2").tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(44100)
            f.writeframes(pcm)
        path.write_bytes(buf.getvalue())
        return wav_bytes(path)
    return wav_bytes(ROOT / "tools" / spec)


def calibrate(force: bool = False) -> bool:
    """Prove the model can identify a recording before believing its verdicts.

    A model that has not passed this has no business grading the palette: MiMo
    scored 0/4 here and handed a real punch a 1/10, and the report it wrote was
    acted on for a whole palette rewrite.
    """
    print(f"calibrating {MODEL} ...")
    passed = 0
    for label, spec, keys in PROBES:
        data, fmt = _probe_clip(spec)
        name = "probe_" + Path(spec).stem.replace("<", "").replace(">", "")
        cache = CACHE / f"{name}_{MODEL.split('/')[-1]}_{digest(data)}_cal.txt"
        if cache.exists() and not force:
            text = cache.read_text()
        else:
            text = critique(name, data, fmt, PROBE_PROMPT)
            CACHE.mkdir(parents=True, exist_ok=True)
            cache.write_text(text)
        low = text.lower()
        ok = any(k in low for k in keys)
        passed += ok
        print(f"  {'ok ' if ok else 'XX '} {label}: {text.strip()[:90]}")
    verdict = passed >= 3
    print(f"  calibration: {passed}/{len(PROBES)} "
          f"{'PASS - this model hears the clips' if verdict else 'FAIL - do not trust its verdicts'}")
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--group", default="sfx", choices=["sfx", "voice", "music"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default="", help="write the report to this path")
    ap.add_argument("--calibrate", action="store_true",
                    help="only run the hearing test, then stop")
    ap.add_argument("--no-calibrate", action="store_true",
                    help="audit without proving the model can hear")
    args = ap.parse_args()

    if args.calibrate:
        return 0 if calibrate(force=args.force) else 1

    if not args.no_calibrate and not calibrate():
        print("\nrefusing to grade the palette with a model that cannot "
              "identify a recorded punch, a bell or a sine tone.\n"
              "Re-run with --no-calibrate to override, and say so in the "
              "report if you do.")
        return 1

    def events(group: str) -> dict:
        return {"sfx": SFX_EVENTS, "voice": VOICE_EVENTS,
                "music": MUSIC_EVENTS}[group]

    if args.group == "sfx":
        paths = [SFX_DIR / f"{n}.wav" for n in
                 (args.only.split(",") if args.only else
                  [p.stem for p in sorted(SFX_DIR.glob("*.wav"))])]
    elif args.group == "voice":
        paths = [VOICE_DIR / f"{n}.wav" for n in
                 (args.only.split(",") if args.only else
                  [p.stem for p in sorted(VOICE_DIR.glob("*.wav"))])]
    else:
        paths = [MUSIC_DIR / f"{n}.wav" for n in
                 (args.only.split(",") if args.only else
                  [p.stem for p in sorted(MUSIC_DIR.glob("*.wav"))])]

    lines = []
    for path in paths:
        if not path.exists():
            print(f"missing {path}")
            continue
        event = events(args.group).get(path.stem, path.stem.replace("_", " "))
        text = audit(path, brief(args.group, event), args.force)
        block = f"### {path.stem}\n{text}\n"
        print(block)
        lines.append(block)
    if args.out:
        Path(args.out).write_text("\n".join(lines))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
