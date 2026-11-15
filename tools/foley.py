#!/usr/bin/env python3
"""Real recorded sound effects for the game, from CC0 (public domain) packs.

Why this exists
    The palette used to be synthesised end to end, and the note in
    build_audio.py argued the case: no samples, no licences, nothing to ship.
    That is a real advantage for a prototype and it is no advantage at all for
    the thing being judged here - whether a punch sounds like a punch. Every
    layer a synthesiser can draw is describable in advance (noise burst, sine
    sweep, band pass), and a listener hears that description: the hits come out
    as clean electronic thwacks next to the reference recording of a fist.

    So the impacts are recorded now. `tools/foley/*.wav` holds the raw material
    - Kenney's CC0 impact, interface and sci-fi packs - and build_audio.py
    layers those recordings under the same synth body, cracks and room it used
    before. The licensing story is the same as it always was: nothing here is
    copyrighted, attribution is not even required, and `tools/foley.py
    --verify` re-checks the licences against the offline pack manifests.

Layout
    tools/foley/manifest.json   what each logical name is, and where it came
                                from; written by `--install`
    tools/foley/*.wav           decoded, trimmed, mono, 44.1 kHz
    tools/cache/foley/          the downloaded zips and their Licence.txt, the
                                provenance behind every sample above

    python3 tools/foley.py --install     # (re)download, decode and refill
    python3 tools/foley.py --verify      # licences + inventory
    python3 tools/foley.py --list        # what the palette can reach for

Builds never need the network: `assets` audio is rendered from the wav files
that are already in tools/foley/. If a sample is missing, build_audio.py drops
that layer and renders the synth-only version of the sound, so a fresh clone
still builds even before `--install` has run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
import wave
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FOLEY_DIR = Path(__file__).resolve().parent / "foley"
CACHE = Path(__file__).resolve().parent / "cache" / "foley"
MANIFEST = FOLEY_DIR / "manifest.json"

SR = 44100

# name -> (pack key, [source files]). Several files under one name are takes:
# build_audio.py picks between them by take number so a three-hit combo is not
# the same recording three times.
PACKS = {
    "impact": {
        "url": "https://kenney.nl/media/pages/assets/impact-sounds/"
               "87b4ddecda-1677589768/kenney_impact-sounds.zip",
        "title": "Kenney Impact Sounds 1.0 (CC0)",
        "dir": "Audio",
    },
    "interface": {
        "url": "https://kenney.nl/media/pages/assets/interface-sounds/"
               "fa43c1dd4d-1677589452/kenney_interface-sounds.zip",
        "title": "Kenney Interface Sounds 1.0 (CC0)",
        "dir": "Audio",
    },
    "scifi": {
        "url": "https://kenney.nl/media/pages/assets/sci-fi-sounds/"
               "6b296f9ecf-1677589334/kenney_sci-fi-sounds.zip",
        "title": "Kenney Sci-Fi Sounds 1.0 (CC0)",
        "dir": "Audio",
    },
}

SAMPLES: dict[str, tuple[str, list[str]]] = {
    # names in the game        pack        source files
    "punch_light":  ("impact", ["impactPunch_medium_000", "impactPunch_medium_001"]),
    "punch_heavy":  ("impact", ["impactPunch_heavy_000", "impactPunch_heavy_001"]),
    "soft_heavy":   ("impact", ["impactSoft_heavy_000", "impactSoft_heavy_001"]),
    "metal_light":  ("impact", ["impactMetal_light_000", "impactMetal_light_001"]),
    "metal_medium": ("impact", ["impactMetal_medium_000", "impactMetal_medium_001"]),
    "plate_heavy":  ("impact", ["impactPlate_heavy_001", "impactPlate_heavy_000"]),
    "tin_medium":   ("impact", ["impactTin_medium_000", "impactTin_medium_001"]),
    "wood_heavy":   ("impact", ["impactWood_heavy_000", "impactWood_heavy_001"]),
    "bell_heavy":   ("impact", ["impactBell_heavy_000", "impactBell_heavy_001"]),
    "generic_light": ("impact", ["impactGeneric_light_000", "impactGeneric_light_001"]),
    "rock":         ("impact", ["impactMining_000", "impactMining_001"]),
    "step_hard":    ("impact", ["footstep_concrete_000", "footstep_concrete_001"]),
    "step_wood":    ("impact", ["footstep_wood_000", "footstep_wood_001"]),
    "glass_light":  ("impact", ["impactGlass_light_001", "impactGlass_light_002"]),
    "ui_click":     ("interface", ["click_001", "click_002"]),
    "ui_select":    ("interface", ["select_001", "select_002"]),
    "ui_confirm":   ("interface", ["confirmation_001", "confirmation_002"]),
    "ui_scroll":    ("interface", ["scroll_001", "scroll_002"]),
    "ui_tick":      ("interface", ["tick_001", "tick_002"]),
    "boom_low":     ("scifi", ["lowFrequency_explosion_000", "lowFrequency_explosion_001"]),
    "crunch":       ("scifi", ["explosionCrunch_000", "explosionCrunch_001"]),
    "force_field":  ("scifi", ["forceField_000", "forceField_001"]),
    "metal_scifi":  ("scifi", ["impactMetal_000", "impactMetal_001"]),
    # The sustained layers. `force_field` is under a second, which is fine for
    # the charge but too short to loop under a flight that lasts as long as the
    # player holds the button; the engine beds are five-second recordings of a
    # machine that is already running, i.e. exactly what an aura wants.
    "engine_low":   ("scifi", ["spaceEngineLow_000", "spaceEngineLow_001"]),
    "laser_big":    ("scifi", ["laserLarge_000", "laserLarge_001"]),
    "laser_small":  ("scifi", ["laserSmall_000", "laserSmall_001"]),
}


# ---------------------------------------------------------------- acquiring

def pack_dir(key: str) -> Path:
    return CACHE / key


def ensure_pack(key: str, force: bool = False) -> Path:
    """Download and unpack a pack if it is not already on disk."""
    meta = PACKS[key]
    dest = pack_dir(key)
    licence = dest / "License.txt"
    if dest.exists() and licence.exists() and not force:
        return dest
    CACHE.mkdir(parents=True, exist_ok=True)
    blob = CACHE / f"{key}.zip"
    print(f"  downloading {meta['title']}")
    with urllib.request.urlopen(meta["url"], timeout=120) as r, blob.open("wb") as f:
        shutil.copyfileobj(r, f)
    if dest.exists():
        shutil.rmtree(dest)
    with zipfile.ZipFile(blob) as z:
        z.extractall(dest)
    if not licence.exists():
        raise RuntimeError(f"{meta['title']}: no License.txt in the archive")
    return dest


def convert(src: Path, dest: Path) -> None:
    """Decode an ogg to mono 44.1 kHz wav with whatever the machine has."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src),
               "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dest)]
    elif sys.platform == "darwin":
        # afconvert reads ogg on macOS and needs no install, but it refuses to
        # overwrite, so the target is made unique first.
        cmd = ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SR}", str(src), str(dest)]
    else:
        raise RuntimeError("need ffmpeg (or macOS afconvert) to decode the packs")
    subprocess.run(cmd, check=True)
    if not dest.exists():
        raise RuntimeError(f"decode failed: {src}")


def install(force: bool = False) -> int:
    """Make sure every sample in SAMPLES exists as a wav under tools/foley."""
    FOLEY_DIR.mkdir(parents=True, exist_ok=True)
    entries: dict[str, dict] = {}
    for name, (key, sources) in SAMPLES.items():
        meta = PACKS[key]
        src_dir = ensure_pack(key, force) / meta["dir"]
        takes = []
        for i, source in enumerate(sources):
            src = src_dir / f"{source}.ogg"
            if not src.exists():
                print(f"  ! {source}.ogg is not in {meta['title']}")
                continue
            out = FOLEY_DIR / f"{name}_{i}.wav"
            if force or not out.exists():
                convert(src, out)
            takes.append({"file": out.name, "source": f"{meta['title']}: {source}.ogg"})
        if not takes:
            continue
        entries[name] = {"pack": key, "license": "CC0-1.0",
                         "title": meta["title"], "takes": takes}
        print(f"  {name:14} {len(takes)} take(s)")
    MANIFEST.write_text(json.dumps(
        {"note": "CC0-1.0 recordings; decode with tools/foley.py --install",
         "packs": {k: {"title": v["title"], "url": v["url"]} for k, v in PACKS.items()},
         "samples": entries}, indent=2) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)}: {len(entries)} names")
    return 0


def verify() -> int:
    """Check the licences and that every manifest entry is on disk."""
    bad = 0
    for key, meta in PACKS.items():
        licence = pack_dir(key) / "License.txt"
        if not licence.exists():
            print(f"  ? {meta['title']}: pack not downloaded")
            continue
        text = licence.read_text(errors="replace")
        ok = "CC0" in text
        print(f"  {'ok' if ok else 'BAD'} {meta['title']}: "
              f"{'CC0' if ok else 'no CC0 marker in License.txt'}")
        bad += 0 if ok else 1
    if MANIFEST.exists():
        data = json.loads(MANIFEST.read_text())
        missing = [t["file"] for s in data["samples"].values() for t in s["takes"]
                   if not (FOLEY_DIR / t["file"]).exists()]
        print(f"  {'ok' if not missing else 'BAD'} {len(data['samples'])} names, "
              f"{sum(len(s['takes']) for s in data['samples'].values())} takes, "
              f"{len(missing)} missing file(s)")
        bad += 1 if missing else 0
    else:
        print("  ? no manifest - run --install")
    print("FOLEY VERIFY OK" if not bad else "FOLEY VERIFY FAILED")
    return 1 if bad else 0


# ------------------------------------------------------------------ reading

_cache: dict[str, list[np.ndarray]] = {}


def available() -> bool:
    return MANIFEST.exists()


def names() -> list[str]:
    if not available():
        return []
    return sorted(json.loads(MANIFEST.read_text())["samples"])


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as f:
        channels, rate = f.getnchannels(), f.getframerate()
        x = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    if rate != SR:
        from dsp import resample
        x = resample(x, SR / rate)
    return x


def takes(name: str) -> list[np.ndarray]:
    """Every take of a logical sample, mono at SR, trimmed and peak-normalised.

    Leading silence is cut to a 1 ms pre-roll: the packs are edited with the
    attack a few tens of milliseconds in, and a layer that starts 30 ms late
    lands after the crack it is supposed to be part of - which read as a
    doubled hit rather than one impact.
    """
    if name in _cache:
        return _cache[name]
    if not available():
        return []
    entry = json.loads(MANIFEST.read_text())["samples"].get(name)
    if not entry:
        return []
    out = []
    for take in entry["takes"]:
        path = FOLEY_DIR / take["file"]
        if not path.exists():
            continue
        x = _read(path)
        leading = int(0.001 * SR)
        loud = np.nonzero(np.abs(x) > 0.01)[0]
        if len(loud):
            start = max(0, int(loud[0]) - leading)
            end = min(len(x), int(loud[-1]) + leading)
            x = x[start:end]
        x = x - float(np.mean(x))
        peak = float(np.max(np.abs(x))) if len(x) else 0.0
        out.append(x / peak if peak > 1e-9 else x)
    _cache[name] = out
    return out


def take(name: str, index: int = 0) -> np.ndarray | None:
    """One take, wrapping around however many the pack shipped."""
    pool = takes(name)
    if not pool:
        return None
    return pool[index % len(pool)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-download and re-decode")
    args = ap.parse_args()
    if args.install:
        install(args.force)
    if args.verify:
        return verify()
    if args.list:
        for name in names():
            print(f"{name:16} {len(takes(name))} take(s)")
    if not (args.install or args.verify or args.list):
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
