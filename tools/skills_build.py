#!/usr/bin/env python3
"""Turn the designer-facing skill configs into the table the game loads.

    python3 tools/skills_build.py            # validate + generate + report
    python3 tools/skills_build.py --check    # validate only, fail if stale
    python3 tools/skills_build.py --quiet    # only errors

Source of truth:  data/skills/<slug>.json        what a designer edits by hand
Generated:        data/characters.generated.json what the game loads at boot

The split exists so that a bad edit is caught here, in a tool that can say
"punch_3 的 pose 是 kickk，美术清单里没有这个姿势", instead of in the game
where a missing pose silently falls back to the code-drawn rig and a bad sfx
name silently plays nothing. Every check below is a mistake that was actually
possible before this file existed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "data" / "skills"
OUT_PATH = ROOT / "data" / "characters.generated.json"
SFX_SCRIPT = ROOT / "scripts" / "sfx.gd"
MANIFEST = ROOT / "assets" / "characters" / "manifest.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import art_spec  # noqa: E402

SLOTS = ["basic", "air", "skill_1", "skill_2", "jutsu", "ultimate"]
KINDS = {
    # kind -> the hit sound and the effects the runtime picks for it
    "light": "hit_light",
    "medium": "hit_medium",
    "heavy": "hit_heavy",
    "launcher": "launcher",
    "chakra": "chakra_hit",
}
CANCEL_ON = ["any", "hit", "block"]


class Fail(RuntimeError):
    pass


# ------------------------------------------------------------------ loading

def designer_keys(d: dict) -> dict:
    """Drop comment keys (`_note`, `_readme`, ...) at every level."""
    out = {}
    for k, v in d.items():
        if str(k).startswith("_"):
            continue
        out[k] = designer_keys(v) if isinstance(v, dict) else v
    return out


def load_sources() -> list[tuple[Path, dict]]:
    files = sorted(SRC_DIR.glob("*.json"))
    if not files:
        raise Fail(f"没有找到任何配置：{SRC_DIR}/*.json")
    out = []
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Fail(f"{path.name} 不是合法 JSON：{exc}") from exc
        out.append((path, designer_keys(raw)))
    return out


def source_hash(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def sfx_ids() -> tuple[set[str], set[str]]:
    """Read the sound palette out of scripts/sfx.gd.

    The palette is the whitelist: play_at() / say() drop unknown names, so a
    typo in a config would be silent rather than loud. Parsing the script is
    ugly but keeps one source of truth - the alternative is a second list that
    drifts out of date the first time somebody adds a sound.
    """
    text = SFX_SCRIPT.read_text(encoding="utf-8")
    events: set[str] = set()
    voice: set[str] = set()
    current = None
    for line in text.splitlines():
        if line.startswith("const EVENTS"):
            current = events
            continue
        if line.startswith("const VOICE_LINES"):
            current = voice
            continue
        if line.startswith("}"):
            current = None
            continue
        if current is None:
            continue
        m = re.match(r'\s*"([A-Za-z0-9_]+)"\s*:', line)
        if m:
            current.add(m.group(1))
    if not events or not voice:
        raise Fail(f"没能从 {SFX_SCRIPT} 里解析出音效白名单")
    return events, voice


def art_poses() -> set[str]:
    return {p["key"] for p in art_spec.POSES}


def manifest_poses() -> dict[str, set[str]]:
    if not MANIFEST.exists():
        return {}
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {slug: set(entry.get("poses", {})) for slug, entry in data.items()}


# --------------------------------------------------------------- validation

def need(cfg: dict, key: str, where: str, errors: list[str]):
    if key not in cfg:
        errors.append(f"{where}: 缺少必填字段 {key}")
        return None
    return cfg[key]


def check_int(value, where: str, errors: list[str], *, minimum: int) -> bool:
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(f"{where}: 必须是整数帧，现在是 {value!r}")
        return False
    if value < minimum:
        errors.append(f"{where}: 不能小于 {minimum} 帧，现在是 {value}")
        return False
    return True


def check_number(value, where: str, errors: list[str]) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{where}: 必须是数字，现在是 {value!r}")
        return False
    return True


def validate(cfg: dict, slug: str, poses: set[str], events: set[str],
             voice: set[str], manifest: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if cfg.get("slug") != slug:
        errors.append(f"slug 字段是 {cfg.get('slug')!r}，但文件名是 {slug}.json")

    stats = need(cfg, "stats", slug, errors) or {}
    for key in ["hp", "energy_max", "energy_start", "energy_regen_per_sec",
                "energy_on_hit", "walk_speed", "air_speed", "jump_speed",
                "fly_speed", "fly_drain_per_sec", "fastfall_speed"]:
        if key not in stats:
            errors.append(f"{slug}.stats: 缺少 {key}")
        elif check_number(stats[key], f"{slug}.stats.{key}", errors):
            if key in ("hp", "energy_max") and stats[key] <= 0:
                errors.append(f"{slug}.stats.{key}: 必须大于 0")
    hb = stats.get("hurtbox")
    if not isinstance(hb, dict) or "w" not in hb or "h" not in hb:
        errors.append(f"{slug}.stats.hurtbox: 需要 {{w, h}}")
    energy_max = float(stats.get("energy_max", 100.0))

    moves = need(cfg, "moves", slug, errors) or []
    if not isinstance(moves, list) or not moves:
        errors.append(f"{slug}.moves: 至少要有一招")
        return errors, warnings

    by_id: dict[str, dict] = {}
    for i, move in enumerate(moves):
        where = f"{slug}.moves[{i}]"
        if not isinstance(move, dict):
            errors.append(f"{where}: 必须是对象")
            continue
        mid = move.get("id")
        if not mid:
            errors.append(f"{where}: 缺少 id")
            continue
        where = f"{slug}.{mid}"
        if mid in by_id:
            errors.append(f"{where}: id 重复")
        by_id[mid] = move

        if not str(move.get("name", "")).strip():
            warnings.append(f"{where}: 没写 name，报告里只能显示 id")

        pose = move.get("pose")
        if pose not in poses:
            errors.append(f"{where}: pose={pose!r} 不在 art_spec.POSES 里（{sorted(poses)}）")
        elif manifest and slug in manifest and pose not in manifest[slug]:
            errors.append(f"{where}: pose={pose!r} 在美术清单 manifest.json 里没有 {slug} 的图")

        kind = move.get("kind")
        if kind not in KINDS:
            errors.append(f"{where}: kind={kind!r} 不合法（可选 {sorted(KINDS)}）")

        for key in ["startup_f", "active_f", "recovery_f"]:
            if key not in move:
                errors.append(f"{where}: 缺少 {key}")
            else:
                check_int(move[key], f"{where}.{key}", errors, minimum=1 if key != "recovery_f" else 0)
        for key in ["hitstun_f", "blockstun_f", "hitstop_f", "cooldown_f"]:
            if key in move:
                check_int(move[key], f"{where}.{key}", errors, minimum=0)
        if "cancel_from_f" in move and "cancel_to_f" in move:
            if check_int(move["cancel_from_f"], f"{where}.cancel_from_f", errors, minimum=0) and \
               check_int(move["cancel_to_f"], f"{where}.cancel_to_f", errors, minimum=0):
                total = int(move.get("startup_f", 0)) + int(move.get("active_f", 0)) + int(move.get("recovery_f", 0))
                if move["cancel_from_f"] > move["cancel_to_f"] and move["cancel_to_f"] != 0:
                    errors.append(f"{where}: cancel_from_f 比 cancel_to_f 还大")
                if move["cancel_to_f"] >= total and move["cancel_into"]:
                    errors.append(f"{where}: 取消窗口到第 {move['cancel_to_f']} 帧，但整招只有 {total} 帧")

        if move.get("cancel_on", "any") not in CANCEL_ON:
            errors.append(f"{where}: cancel_on 只能是 {CANCEL_ON}")
        if move.get("cancel_into") and not move.get("cancel_into"):
            errors.append(f"{where}: cancel_into 必须是数组")

        for key in ["damage", "cost"]:
            if key in move and check_number(move[key], f"{where}.{key}", errors):
                if move[key] < 0:
                    errors.append(f"{where}.{key}: 不能是负数")
        if isinstance(move.get("cost"), (int, float)) and move["cost"] > energy_max:
            errors.append(f"{where}.cost: {move['cost']} 超过了 energy_max={energy_max}")

        if "air_ok" in move and not isinstance(move["air_ok"], bool):
            errors.append(f"{where}.air_ok: 必须是 true/false")
        elif "air_ok" not in move:
            errors.append(f"{where}: 缺少 air_ok")

        if "fx_color" in move:
            rgb = move["fx_color"]
            if not isinstance(rgb, list) or len(rgb) != 3 or any(
                    not isinstance(v, (int, float)) or isinstance(v, bool) or float(v) < 0.0 or float(v) > 1.0
                    for v in rgb):
                errors.append(f"{where}.fx_color: 必须是三个 0 到 1 之间的数字")

        box = move.get("hitbox")
        if box is not None:
            if not isinstance(box, dict) or not all(k in box for k in ("x", "y", "w", "h")):
                errors.append(f"{where}.hitbox: 需要 {{x, y, w, h}}（判定框以脚底为原点，Y 向上为负）")
            else:
                for k in ("w", "h"):
                    if check_number(box[k], f"{where}.hitbox.{k}", errors) and box[k] <= 0:
                        errors.append(f"{where}.hitbox.{k}: 必须大于 0")

        kb = move.get("knockback")
        if not isinstance(kb, dict) or "x" not in kb or "y" not in kb:
            errors.append(f"{where}.knockback: 需要 {{x, y}}")

        sfx = move.get("sfx")
        if sfx is not None and sfx not in events:
            errors.append(f"{where}.sfx: {sfx!r} 不在 sfx.gd 的 EVENTS 白名单里")
        line = move.get("voice")
        if line is not None and line not in voice:
            errors.append(f"{where}.voice: {line!r} 不在 sfx.gd 的 VOICE_LINES 白名单里")

        proj = move.get("projectile")
        if proj is not None:
            if not isinstance(proj, dict):
                errors.append(f"{where}.projectile: 必须是对象或 null")
            else:
                for key in ["damage", "speed", "radius"]:
                    if key not in proj:
                        errors.append(f"{where}.projectile: 缺少 {key}")
                if "life_f" not in proj:
                    errors.append(f"{where}.projectile: 缺少 life_f（帧）")
                else:
                    check_int(proj["life_f"], f"{where}.projectile.life_f", errors, minimum=1)
                for key in ["hit_sfx", "spawn_sfx", "death_sfx"]:
                    if proj.get(key) is not None and proj[key] not in events:
                        errors.append(f"{where}.projectile.{key}: {proj[key]!r} 不在音效白名单里")
        elif move.get("kind") == "chakra":
            warnings.append(f"{where}: kind 是 chakra 但没有 projectile，这只招不会有飞行道具")

        ai = move.get("ai")
        if not isinstance(ai, dict) or "range" not in ai or "weight" not in ai:
            errors.append(f"{where}.ai: 需要 {{range, weight}}（CPU 用它决定什么时候出这招；"
                          "可选的 min_range 是最近使用距离，默认 0）")
        else:
            if check_number(ai["range"], f"{where}.ai.range", errors):
                if ai["range"] < 0:
                    errors.append(f"{where}.ai.range: 不能是负数")
                elif ai["range"] > 1300:
                    warnings.append(f"{where}.ai.range: {ai['range']:g} 比擂台的宽度还大，等于全屏都能用")
            if "min_range" in ai and check_number(ai["min_range"], f"{where}.ai.min_range", errors):
                if ai["min_range"] < 0:
                    errors.append(f"{where}.ai.min_range: 不能是负数")
                elif check_number(ai["range"], f"{where}.ai.range", []) and \
                        ai["min_range"] > ai["range"]:
                    errors.append(f"{where}.ai: min_range ({ai['min_range']:g}) 比 range "
                                  f"({ai['range']:g}) 还大，这招 CPU 永远不会用")
            if check_number(ai["weight"], f"{where}.ai.weight", errors):
                if ai["weight"] < 0:
                    errors.append(f"{where}.ai.weight: 不能是负数")
                elif ai["weight"] == 0:
                    warnings.append(f"{where}.ai.weight: 是 0，CPU 永远不会选这招")

        for key in ["impulse_x", "impulse_y", "lunge"]:
            if key in move:
                check_number(move[key], f"{where}.{key}", errors)

    # cancel_into 指向的 id 必须存在
    for mid, move in by_id.items():
        for target in move.get("cancel_into", []) or []:
            if target not in by_id:
                errors.append(f"{slug}.{mid}.cancel_into: 指向了不存在的招式 {target!r}")
            elif target == mid:
                errors.append(f"{slug}.{mid}.cancel_into: 取消到自己没有意义")

    slots = need(cfg, "slots", slug, errors) or {}
    used: set[str] = set()
    for name, ids in slots.items():
        if name.startswith("_"):
            continue
        if name not in SLOTS:
            errors.append(f"{slug}.slots: 未知技能槽 {name!r}（可选 {SLOTS}）")
            continue
        if not isinstance(ids, list):
            errors.append(f"{slug}.slots.{name}: 必须是招式 id 数组")
            continue
        if not ids:
            # Not an error - an unfinished character should still run - but a
            # designer looking at the report needs to know the key does nothing.
            warnings.append(f"{slug}.slots.{name}: 这一槽是空的，按对应的键没有任何反应")
        for mid in ids:
            if mid not in by_id:
                errors.append(f"{slug}.slots.{name}: 指向了不存在的招式 {mid!r}")
            else:
                used.add(mid)
                if name == "air" and not by_id[mid].get("air_ok"):
                    errors.append(f"{slug}.slots.air: {mid} 的 air_ok 是 false，空中放不出来")
        # The basic slot is an ordered chain: each step must be able to cancel
        # into the next one, otherwise the string silently breaks in the middle.
        if name == "basic":
            for a, b in zip(ids, ids[1:]):
                if a in by_id and a != b and b not in (by_id[a].get("cancel_into") or []):
                    errors.append(
                        f"{slug}.slots.basic: {a} 接不到 {b}（{a}.cancel_into 里没有它），连段会断"
                    )
    for mid in by_id:
        if mid not in used:
            errors.append(f"{slug}.{mid}: 没有任何技能槽引用它，玩家永远按不出来（id 拼错了？）")

    return errors, warnings


# ------------------------------------------------------------------ report

def verdict(frames: int) -> str:
    if frames >= 5:
        return "可接连段"
    if frames >= 3:
        return "可安全压制"
    if frames >= 1:
        return "微弱有利"
    if frames == 0:
        return "双方同时恢复"
    if frames >= -2:
        return "微弱不利"
    if frames >= -4:
        return "会被快招抢"
    if frames >= -7:
        return "会被中招确反"
    if frames >= -12:
        return "会被重招确反"
    return "吃超必杀"


def advantage(move: dict) -> tuple[int, int]:
    """(on hit, on block) frame advantage, counting the first active frame."""
    remaining = (int(move["active_f"]) - 1) + int(move["recovery_f"])
    return int(move.get("hitstun_f", 0)) - remaining, int(move.get("blockstun_f", 0)) - remaining


def verdict_for(move: dict, frames: int) -> str:
    if move.get("projectile"):
        return "距离相关"
    if move.get("kind") == "launcher":
        return "挑空，看浮空追击窗口"
    return verdict(frames)


def report(cfg: dict) -> str:
    slug = cfg["slug"]
    stats = cfg.get("stats", {})
    lines = [f"\n{cfg.get('display', slug)}（{slug}）  60 帧 = 1 秒"]
    lines.append("  血量 {hp:g}  气 {energy_start:g}/{energy_max:g}（每秒回 {regen:g}，命中回 {on_hit:g}）"
                 .format(hp=float(stats.get("hp", 0)), energy_start=float(stats.get("energy_start", 0)),
                         energy_max=float(stats.get("energy_max", 0)),
                         regen=float(stats.get("energy_regen_per_sec", 0)),
                         on_hit=float(stats.get("energy_on_hit", 0))))
    lines.append("  地面速度 {walk:g}  空中速度 {air:g}  跳跃 {jump:g}  升空 {fly:g}（耗气 {drain:g}/秒）"
                 .format(walk=float(stats.get("walk_speed", 0)), air=float(stats.get("air_speed", 0)),
                         jump=float(stats.get("jump_speed", 0)), fly=float(stats.get("fly_speed", 0)),
                         drain=float(stats.get("fly_drain_per_sec", 0))))
    lines.append("  {:<12}{:<6}{:>4}{:>5}{:>5}{:>5}{:>6}{:>6}{:>5}{:>5}  {}"
                 .format("招式", "槽位", "启动", "活跃", "收招", "总帧", "伤害", "气", "命中", "防御", "含义"))
    for move in cfg["moves"]:
        mid = move["id"]
        slot = next((s for s, ids in cfg["slots"].items()
                     if not str(s).startswith("_") and mid in ids), "-")
        total = int(move["startup_f"]) + int(move["active_f"]) + int(move["recovery_f"])
        on_hit, on_block = advantage(move)
        shot = bool(move.get("projectile"))
        dmg = move.get("damage", 0.0)
        if move.get("projectile"):
            dmg = move["projectile"].get("damage", 0.0)
        lines.append("  {:<12}{:<6}{:>4}{:>5}{:>5}{:>5}{:>6}{:>6}{:>6}{:>6}  {}"
                     .format(mid, slot, move["startup_f"], move["active_f"], move["recovery_f"],
                             total, f"{dmg:g}", f"{move.get('cost', 0):g}",
                             "--" if shot else f"{on_hit:+d}",
                             "--" if shot else f"{on_block:+d}",
                             verdict_for(move, on_hit)))
    return "\n".join(lines)


# ------------------------------------------------------------------- emit

def build() -> dict:
    sources = load_sources()
    events, voice = sfx_ids()
    poses = art_poses()
    manifest = manifest_poses()

    errors: list[str] = []
    warnings: list[str] = []
    characters: dict[str, dict] = {}
    for path, cfg in sources:
        slug = path.stem
        e, w = validate(cfg, slug, poses, events, voice, manifest)
        errors += e
        warnings += w
        # Resolve kind -> hit sound here so the runtime never has to know the
        # mapping, and so a move cannot reach the game with an unresolvable one.
        for move in cfg.get("moves", []) or []:
            if isinstance(move, dict) and move.get("kind") in KINDS:
                move["hit_sfx"] = KINDS[move["kind"]]
                hit, block = advantage(move)
                move["frame_advantage"] = {"on_hit": hit, "on_block": block}
        characters[slug] = cfg
    return {"errors": errors, "warnings": warnings, "characters": characters,
            "sources": [p for p, _ in sources]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只校验，不写生成文件；生成文件过期则失败")
    ap.add_argument("--quiet", action="store_true", help="只打印错误")
    args = ap.parse_args()

    try:
        result = build()
    except Fail as exc:
        print(f"配置构建失败：{exc}", file=sys.stderr)
        return 2

    for w in result["warnings"]:
        print(f"警告  {w}")
    for e in result["errors"]:
        print(f"错误  {e}", file=sys.stderr)
    if result["errors"]:
        print(f"\n{len(result['errors'])} 个错误，没有生成配置。修好 data/skills/*.json 再跑一次。", file=sys.stderr)
        return 1

    digest = source_hash(result["sources"])
    payload = {
        "generated_by": "tools/skills_build.py",
        "version": 1,
        "source_hash": digest,
        "characters": result["characters"],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"

    if args.check:
        current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else ""
        if current != text:
            print("配置已过期：data/characters.generated.json 和 data/skills/ 不一致，"
                  "跑 python3 tools/skills_build.py 重新生成。", file=sys.stderr)
            return 1
        print(f"配置 OK（source_hash={digest}）")
        return 0

    OUT_PATH.write_text(text, encoding="utf-8")
    if not args.quiet:
        for cfg in result["characters"].values():
            print(report(cfg))
        print(f"\n已生成 {OUT_PATH.relative_to(ROOT)}  （source_hash={digest}，"
              f"{len(result['characters'])} 个角色）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
