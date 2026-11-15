#!/usr/bin/env python3
"""Refresh Godot's asset import cache after a render tool rewrote a file.

Godot only re-imports changed assets when the *editor* runs. Launching the game
straight from the command line (`Godot --path .`, the command in the README)
reuses whatever is already in `.godot/imported/` and never looks at the source
file again - so audio rendered by tools/build_audio.py, tools/build_music.py or
tools/gen_voices.py is silently ignored until somebody opens the project in the
editor.

That is how a rebuilt palette can measure clean, pass every gate and still be
inaudible in game: the mixer was solving for a file the runtime never loaded.
The v2 render sat in exactly that state - every .sample under .godot/ was older
than its .wav, and the hammered "muffled boop" palette the rewrite had just
replaced was still the one being played.

`reimport()` shells out to `godot --headless --path <project> --import`, which
starts the editor just long enough to bring the cache up to date and then quits.
A full render calls it automatically; `--no-reimport` skips it. Both
tools/audio_report.py and tests/audio_check.gd fail when a source file is newer
than its imported copy, so a skipped refresh shows up as a red test rather than
as a mysteriously unchanged sound.

    python3 tools/godot_reimport.py            # refresh, then report
    Godot --headless --path . --import         # what it runs
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Where a Godot 4 binary commonly lives on a Mac: the cask install, a manual
# install into ~/Applications, and the throwaway download this project was
# developed against. $GODOT and $PATH are checked first.
CANDIDATES = [
    Path("/Applications/Godot.app/Contents/MacOS/Godot"),
    Path.home() / "Applications" / "Godot.app" / "Contents" / "MacOS" / "Godot",
]


def find_godot() -> str | None:
    """Path to a usable Godot binary, or None when the engine is not installed."""
    override = os.environ.get("GODOT")
    if override and Path(override).exists():
        return override
    on_path = shutil.which("godot")
    if on_path:
        return on_path
    for path in CANDIDATES:
        if path.exists():
            return str(path)
    for path in sorted(Path("/private/tmp").glob("godot*/Godot.app/Contents/MacOS/Godot")):
        if path.exists():
            return str(path)
    return None


def reimport(root: Path | None = None, quiet: bool = False) -> bool:
    """Bring `.godot/imported/` up to date with the files on disk.

    Returns True when the cache was refreshed. A missing engine is a warning,
    not an error: the render tools still work, the sounds are just invisible to
    the game until somebody imports them.
    """
    exe = find_godot()
    if exe is None:
        if not quiet:
            print("  (Godot not found - skipping reimport; set $GODOT or open the "
                  "project in the editor)")
        return False
    project = Path(root) if root is not None else ROOT
    if not quiet:
        print("  refreshing Godot's import cache ...")
    try:
        done = subprocess.run(
            [exe, "--headless", "--path", str(project), "--import"],
            capture_output=True, text=True,
        )
    except OSError as exc:
        if not quiet:
            print(f"  (reimport skipped: {exc})")
        return False
    if done.returncode != 0:
        if not quiet:
            tail = (done.stderr or done.stdout or "").strip().splitlines()[-3:]
            print(f"  (Godot reimport exited {done.returncode}: {' / '.join(tail)})")
        return False
    if not quiet:
        print("  import cache is now newer than every source file")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--project", default="", help="project directory (defaults to this repo)")
    args = ap.parse_args()
    if find_godot() is None:
        print("no Godot binary found; put one on $PATH or set $GODOT")
        return 1
    return 0 if reimport(Path(args.project) if args.project else None, args.quiet) else 1


if __name__ == "__main__":
    sys.exit(main())
