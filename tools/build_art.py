#!/usr/bin/env python3
"""Generate every piece of artwork the game uses.

Pipeline
    1. text -> the character's IDLE pose. This single image becomes the design
       lock for that fighter.
    2. image+text -> every other pose, the KO pose and the HUD portrait, each
       one edited FROM the idle image so the face, costume, colours and line
       style stay identical across all ten sprites.
    3. post-process: clean the alpha, normalise every pose to the same body
       size, anchor it at the feet, emit the white hit-flash copy and rewrite
       assets/characters/manifest.json.
    4. text -> the stage painting (cropped to 16:9 and resized to 1280x720).

Raw model output is cached under tools/cache/ so re-running only regenerates
what is missing; pass --force to redo everything.

    python3 tools/build_art.py                     # fill in anything missing
    python3 tools/build_art.py --chars sora --force
    python3 tools/build_art.py --stage-only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import art_post as post  # noqa: E402
import art_spec as spec  # noqa: E402
import zenmux  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tools" / "cache"
CHARS_DIR = ROOT / "assets" / "characters"
STAGE_DIR = ROOT / "assets" / "stage"
FX_DIR = ROOT / "assets" / "fx"
MANIFEST = CHARS_DIR / "manifest.json"
SPRITE_SCALE = 0.5
IDLE_HEIGHT = 300  # pixels, in sprite space; 0.5 * 300 = 150px tall in game


# ----------------------------------------------------------------- prompts

def idle_prompt(slug: str) -> str:
    c = spec.CHARACTERS[slug]
    return (
        spec.STYLE
        + "Character design: "
        + c["design"]
        + " "
        + spec.FIGHT_VIEW
        + "Pose: "
        + next(p["prompt"] for p in spec.POSES if p["key"] == "idle")
        + " This image must work as the master reference for the character, so keep "
        "the costume details crisp and readable. "
        + spec.FORBID
    )


def pose_prompt(slug: str, pose: dict) -> str:
    c = spec.CHARACTERS[slug]
    return (
        "The attached image is the definitive, approved design of one character: "
        + c["design"]
        + " Redraw that exact same character, keeping the face, hairstyle, forehead "
        "protector, costume, colours, proportions, ink line weight and cel-shading "
        "absolutely identical to the reference image. Change ONLY the pose. "
        + pose["prompt"]
        + " "
        + spec.STYLE
        + " "
        + spec.FIGHT_VIEW
        + spec.FORBID
    )


def portrait_prompt(slug: str) -> str:
    c = spec.CHARACTERS[slug]
    return (
        "The attached image is the definitive, approved design of one character: "
        + c["design"]
        + " Keep the face, hairstyle, forehead protector and costume identical to "
        "the reference image. "
        + spec.PORTRAIT_PROMPT
        + " "
        + spec.STYLE
        + spec.FORBID
    )


# ------------------------------------------------------------- generation

def _cached(path: Path, force: bool) -> bool:
    return path.exists() and path.stat().st_size > 0 and not force


def fetch_idle(slug: str, force: bool, quality: str) -> Path:
    dest = CACHE / slug / "idle.png"
    if _cached(dest, force):
        print(f"  [cache] {slug} idle (design lock)")
        return dest
    print(f"  [gen]   {slug} idle -> design lock")
    png = zenmux.generate(idle_prompt(slug), size="1024x1536", quality=quality)
    return zenmux.save(png, dest)


def fetch_pose(slug: str, pose: dict, ref: Path, force: bool, quality: str) -> Path:
    dest = CACHE / slug / f"{pose['key']}.png"
    if _cached(dest, force):
        print(f"  [cache] {slug} {pose['key']}")
        return dest
    print(f"  [gen]   {slug} {pose['key']}")
    png = zenmux.edit(
        pose_prompt(slug, pose),
        [ref],
        size=pose["size"],
        quality=quality,
        transparent=True,
    )
    return zenmux.save(png, dest)


def fetch_portrait(slug: str, ref: Path, force: bool, quality: str) -> Path:
    dest = CACHE / slug / "portrait.png"
    if _cached(dest, force):
        print(f"  [cache] {slug} portrait")
        return dest
    print(f"  [gen]   {slug} portrait")
    png = zenmux.edit(
        portrait_prompt(slug),
        [ref],
        size="1024x1024",
        quality=quality,
        transparent=False,
    )
    return zenmux.save(png, dest)


def fetch_stage(force: bool, quality: str) -> Path:
    dest = CACHE / "stage" / "dusk_village.png"
    if _cached(dest, force):
        print("  [cache] stage")
        return dest
    print("  [gen]   stage")
    png = zenmux.generate(spec.STAGE_PROMPT, size="1536x1024", quality=quality, transparent=False)
    return zenmux.save(png, dest)


def fetch_fx(name: str, force: bool, quality: str) -> Path:
    fx = spec.FX[name]
    dest = CACHE / "fx" / f"{name}.png"
    if _cached(dest, force):
        print(f"  [cache] fx/{name}")
        return dest
    print(f"  [gen]   fx/{name}")
    png = zenmux.generate(fx["prompt"], size=fx["size"], quality=quality, transparent=True)
    return zenmux.save(png, dest)


def build_fx(name: str, raw: Path) -> None:
    """Trim an effect sprite, cap its size and give it a slightly softer edge."""
    img = post.clean(post.load_rgba(raw))
    s = post.stats(img)
    cropped, _, _ = post.trim(img, img.width / 2.0, s["bbox"])
    longest = max(cropped.size)
    if longest > 512:
        k = 512.0 / longest
        cropped = cropped.resize(
            (max(1, int(cropped.width * k)), max(1, int(cropped.height * k))), Image.LANCZOS
        )
    FX_DIR.mkdir(parents=True, exist_ok=True)
    cropped.save(FX_DIR / f"{name}.png")
    print(f"    fx/{name} -> {cropped.width}x{cropped.height}")


# ------------------------------------------------------------ post-process

def build_sprite(raw: Path, out_base: Path, factor: float = 1.0) -> dict:
    """Clean, scale and trim one raw generation into a game sprite."""
    img = post.clean(post.load_rgba(raw))
    if factor != 1.0:
        img = post.scaled_copy(img, factor)
        img = post.clean(img)
    s = post.stats(img)
    cropped, ax, ay = post.trim(img, s["anchor_x"], s["bbox"])
    out_base.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(out_base)
    post.flash_from(cropped).save(out_base.with_name(out_base.stem + "_flash.png"))
    return {
        "w": cropped.width,
        "h": cropped.height,
        "ax": round(ax, 1),
        "ay": round(ay, 1),
        "raw_h": s["height"],
        "raw_area": s["area"],
        "factor": round(factor, 4),
    }


def build_character(slug: str, char_dir: Path, raw: dict, report: dict) -> dict:
    idle_img = post.clean(post.load_rgba(raw["idle"]))
    ref_stats = post.stats(idle_img)
    base_factor = IDLE_HEIGHT / ref_stats["height"]
    print(
        f"  {slug}: idle silhouette {ref_stats['width']}x{ref_stats['height']}px "
        f"-> normalise x{base_factor:.3f}"
    )

    entry = {"poses": {}, "portrait": f"{slug}/portrait.png", "display": spec.CHARACTERS[slug]["display"]}
    for pose in spec.POSES:
        key = pose["key"]
        src = raw.get(key)
        if src is None:
            continue
        factor = base_factor
        if key != "idle":
            pose_stats = post.stats(post.clean(post.load_rgba(src)))
            factor = base_factor * post.scale_factor(ref_stats, pose_stats, pose["scale"])
        out = char_dir / f"{key}.png"
        info = build_sprite(src, out, factor)
        entry["poses"][key] = {
            "file": f"{slug}/{key}.png",
            "flash": f"{slug}/{key}_flash.png",
            "w": info["w"],
            "h": info["h"],
            "ax": info["ax"],
            "ay": info["ay"],
            "s": SPRITE_SCALE,
        }
        report.setdefault(slug, {})[key] = info
        print(
            f"    {key:<7} raw {info['raw_h']:>4}px  x{info['factor']:.3f}  "
            f"-> {info['w']}x{info['h']}  anchor ({info['ax']}, {info['ay']})"
        )

    portrait_raw = raw.get("portrait")
    if portrait_raw is not None:
        img = Image.open(portrait_raw).convert("RGB")
        side = min(img.size)
        left = (img.width - side) // 2
        top = max(0, int((img.height - side) * 0.30))
        img = img.crop((left, top, left + side, top + side)).resize((640, 640), Image.LANCZOS)
        img.save(char_dir / "portrait.png")
        print(f"    portrait -> 640x640")
    return entry


def build_stage(raw: Path) -> None:
    img = Image.open(raw).convert("RGB")
    target = 16 / 9
    w, h = img.size
    if w / h > target:
        new_w = int(h * target)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target)
        top = int((h - new_h) * 0.45)
        img = img.crop((0, top, w, top + new_h))
    img = img.resize((1280, 720), Image.LANCZOS)
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    img.save(STAGE_DIR / "dusk_village.png")
    print("    stage -> 1280x720")


def contact_sheet(manifest: dict) -> Path:
    """A side-by-side board of every sprite, drawn at in-game scale."""
    keys = [p["key"] for p in spec.POSES]
    cell_w, cell_h = 260, 260
    sheet = Image.new("RGB", (cell_w * len(keys), cell_h * 2 + 60), (18, 16, 26))
    draw = ImageDraw.Draw(sheet)
    for row, slug in enumerate(["sora", "kaze"]):
        if slug not in manifest:
            continue
        base_y = row * cell_h + cell_h - 20
        draw.text((10, row * cell_h + 6), slug.upper(), fill=(240, 235, 255))
        draw.line([(0, base_y), (sheet.width, base_y)], fill=(90, 90, 130), width=2)
        for col, key in enumerate(keys):
            info = manifest[slug]["poses"].get(key)
            if not info:
                continue
            path = CHARS_DIR / info["file"]
            if not path.exists():
                continue
            sprite = Image.open(path).convert("RGBA").resize(
                (max(1, int(info["w"] * SPRITE_SCALE)), max(1, int(info["h"] * SPRITE_SCALE))),
                Image.LANCZOS,
            )
            x = col * cell_w + cell_w // 2 - int(info["ax"] * SPRITE_SCALE)
            y = base_y - int(info["ay"] * SPRITE_SCALE)
            sheet.paste(sprite, (x, y), sprite)
            draw.text((col * cell_w + 6, row * cell_h + 22), key, fill=(170, 165, 200))
        # Same-height ruler so scale drift between poses is obvious.
        for col in range(1, len(keys)):
            draw.line(
                [(col * cell_w, 0), (col * cell_w, sheet.height)], fill=(44, 42, 62), width=1
            )
    out = ROOT / "docs" / "art_contact_sheet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print("    contact sheet ->", out.relative_to(ROOT))
    return out


# -------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the game's anime artwork.")
    ap.add_argument("--chars", default="sora,kaze", help="comma separated character slugs")
    ap.add_argument("--jobs", type=int, default=4, help="parallel API requests")
    ap.add_argument("--quality", default="high", choices=["low", "medium", "high"])
    ap.add_argument("--force", action="store_true", help="ignore the cache")
    ap.add_argument("--stage-only", action="store_true")
    ap.add_argument("--fx-only", action="store_true")
    ap.add_argument("--no-stage", action="store_true")
    ap.add_argument("--no-fx", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the prompts and exit")
    args = ap.parse_args()

    slugs = [s.strip() for s in args.chars.split(",") if s.strip()]

    if args.dry_run:
        for slug in slugs:
            print("=" * 70)
            print("IDLE /", slug)
            print(idle_prompt(slug))
            for pose in spec.POSES:
                if pose["key"] == "idle":
                    continue
                print("-" * 70)
                print("POSE /", pose["key"])
                print(pose_prompt(slug, pose))
            print("-" * 70)
            print("PORTRAIT /", slug)
            print(portrait_prompt(slug))
        print("=" * 70)
        print("STAGE")
        print(spec.STAGE_PROMPT)
        return 0

    started = time.time()
    report: dict = {}

    if args.stage_only:
        raw = fetch_stage(args.force, args.quality)
        build_stage(raw)
        print(f"done in {time.time() - started:.0f}s")
        return 0

    if args.fx_only:
        print("[fx]")
        for name in spec.FX:
            try:
                build_fx(name, fetch_fx(name, args.force, args.quality))
            except Exception as exc:
                print(f"  !! fx/{name} failed: {exc}")
        print(f"done in {time.time() - started:.0f}s")
        return 0

    manifest = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())

    for slug in slugs:
        print(f"[{slug}]")
        ref = fetch_idle(slug, args.force, args.quality)
        raw = {"idle": ref}

        todo = [p for p in spec.POSES if p["key"] != "idle"]
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {
                pool.submit(fetch_pose, slug, pose, ref, args.force, args.quality): pose
                for pose in todo
            }
            futures[pool.submit(fetch_portrait, slug, ref, args.force, args.quality)] = None
            for fut in as_completed(futures):
                pose = futures[fut]
                try:
                    path = fut.result()
                except Exception as exc:  # keep the run going, report at the end
                    label = pose["key"] if pose else "portrait"
                    print(f"  !! {slug} {label} failed: {exc}")
                    continue
                raw[pose["key"] if pose else "portrait"] = path

        char_dir = CHARS_DIR / slug
        manifest[slug] = build_character(slug, char_dir, raw, report)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print("[manifest] assets/characters/manifest.json")

    if not args.no_stage:
        print("[stage]")
        try:
            build_stage(fetch_stage(args.force, args.quality))
        except Exception as exc:
            print("  !! stage failed:", exc)

    if not args.no_fx:
        print("[fx]")
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {
                pool.submit(fetch_fx, name, args.force, args.quality): name
                for name in spec.FX
            }
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    build_fx(name, fut.result())
                except Exception as exc:
                    print(f"  !! fx/{name} failed: {exc}")

    contact_sheet(manifest)
    (ROOT / "docs" / "art_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"done in {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
