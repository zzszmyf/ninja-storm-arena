#!/usr/bin/env python3
"""Sanity-check that each generated pose actually matches its gameplay meaning.

The image model is asked for a specific action per pose (a punch reaches
forward at chest height, a roundhouse kick reaches forward at head height, a
KO lies flat...). This script measures the silhouette and prints how far the
body reaches to the RIGHT of the character's own anchor in each height band,
which is what "a punch is extended" means geometrically.

    python3 tools/check_poses.py            # table for both fighters
    python3 tools/check_poses.py --strict   # non-zero exit if a check fails
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CHARS_DIR = ROOT / "assets" / "characters"
MANIFEST = CHARS_DIR / "manifest.json"

# Vertical bands, as a fraction of the silhouette height measured from the top
# of the sprite, used to isolate the limb that should be extended.
BANDS = {
    "head": (0.02, 0.28),
    "chest": (0.22, 0.50),
    "waist": (0.25, 0.55),
    "legs": (0.45, 0.85),
}


def profile(path: Path, info: dict) -> dict:
    arr = np.array(Image.open(path).convert("RGBA"))
    mask = arr[:, :, 3] > 32
    if not mask.any():
        return {"empty": True}
    ys, xs = np.nonzero(mask)
    top, bottom = ys.min(), ys.max() + 1
    height = bottom - top
    ax = float(info["ax"])
    body_height = float(info["h"])  # sprite pixel height after trim
    reach = {}
    for name, (b0, b1) in BANDS.items():
        band = mask[top + int(height * b0) : top + int(height * b1), :]
        if not band.any():
            reach[name] = 0.0
            continue
        right = float(np.nonzero(band)[1].max())
        reach[name] = (right - ax) / height  # in body-heights
    return {
        "empty": False,
        "height": height,
        "aspect": round(mask.shape[1] / max(1, height), 2),
        "solidity": round(float(mask.sum()) / (height * (xs.max() - xs.min() + 1)), 2),
        "anchor_frac": round(ax / mask.shape[1], 3),
        "reach": reach,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="fail when a pose looks wrong")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    failures = []
    for slug, entry in sorted(manifest.items()):
        print(f"== {slug}")
        poses = entry["poses"]
        measured = {}
        for pose, info in sorted(poses.items()):
            path = CHARS_DIR / info["file"]
            if not path.exists():
                failures.append(f"{slug}/{pose}: file missing")
                continue
            p = profile(path, info)
            if p.get("empty"):
                failures.append(f"{slug}/{pose}: empty silhouette")
                continue
            measured[pose] = p
            reach = p["reach"]
            detail = " ".join(f"{k}={v:+.2f}" for k, v in sorted(reach.items()))
            print(
                f"  {pose:<7} h={p['height']:>4} aspect={p['aspect']:>5} "
                f"solidity={p['solidity']:.2f} anchor={p['anchor_frac']:.2f} | {detail}"
            )
            # Every fighter should keep a sane, feet-anchored placement.
            if not 0.25 <= p["anchor_frac"] <= 0.75:
                failures.append(f"{slug}/{pose}: anchor at {p['anchor_frac']:.2f} looks off-centre")

        # Pose accuracy is judged RELATIVE to the idle sprite of the same
        # fighter: absolute measurements depend on how the model framed the
        # shot, but "the punch reaches further than the idle stance" does not.
        idle = measured.get("idle")
        if idle is None:
            failures.append(f"{slug}: no idle pose to calibrate against")
            continue
        for pose, band, gain in (
            ("attack", "chest", 0.14),   # straight punch at chest height
            ("proj", "waist", 0.12),     # both palms thrust forward
            ("kick", "head", 0.20),      # roundhouse at head height
        ):
            p = measured.get(pose)
            if p is None:
                continue
            if p["reach"][band] - idle["reach"][band] < gain:
                failures.append(
                    f"{slug}/{pose}: reaches only "
                    f"{p['reach'][band] - idle['reach'][band]:+.2f} body-heights past the "
                    f"idle {band} (want >= {gain:+.2f}) - the limb may not be extended"
                )
        # Tucked / horizontal poses.
        for pose, max_ratio in (("air", 0.88), ("ko", 0.75)):
            p = measured.get(pose)
            if p and p["height"] > idle["height"] * max_ratio:
                failures.append(
                    f"{slug}/{pose}: silhouette is {p['height'] / idle['height']:.2f}x the "
                    f"idle height (want <= {max_ratio:.2f}x)"
                )
        ko = measured.get("ko")
        if ko and ko["aspect"] < 1.3:
            failures.append(f"{slug}/ko: aspect {ko['aspect']} does not read as a lying body")
        run = measured.get("run")
        if run and run["aspect"] < idle["aspect"]:
            failures.append(f"{slug}/run: aspect {run['aspect']} is narrower than idle - no lean")

    if failures:
        print("\nPOSE CHECK FAILURES:")
        for f in failures:
            print("  -", f)
        return 1 if args.strict else 0
    print("\nPOSE CHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
