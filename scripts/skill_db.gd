extends RefCounted

# Deliberately no `class_name`: the global class cache in .godot/ is only
# refreshed when the editor scans the project, so a file added from outside the
# editor is invisible to the running game until somebody opens it. Consumers
# preload this script instead, which always works.

# Loads the generated skill table that tools/skills_build.py writes.
#
# The game never reads data/skills/*.json: designers edit those, the build tool
# validates them and writes data/characters.generated.json, and this file is the
# only thing that reads the result. That way a bad edit fails in the tool with a
# readable message instead of half-working in the game.
#
# If the generated file is missing or corrupt the game still boots on a small
# built-in table, because "the config is stale" should mean "your damage numbers
# are old", not "you cannot play".

const PATH := "res://data/characters.generated.json"
const FPS := 60.0
const SLOTS := ["basic", "air", "skill_1", "skill_2", "jutsu", "ultimate"]
# The slots the CPU is allowed to fire, and the order it considers them in.
# `basic` and `air` are driven by the attack button, which chains on its own.
const AI_SLOTS := ["ultimate", "jutsu", "skill_2", "skill_1"]

static var _characters: Dictionary = {}
static var _loaded := false
static var _source_hash := ""


static func _load() -> void:
	if _loaded:
		return
	_loaded = true
	if FileAccess.file_exists(PATH):
		var parsed = JSON.parse_string(FileAccess.get_file_as_string(PATH))
		if parsed is Dictionary and parsed.get("characters") is Dictionary:
			_characters = parsed["characters"]
			_source_hash = String(parsed.get("source_hash", ""))
			return
		push_error("技能配置损坏：%s" % PATH)
	else:
		push_error("技能配置缺失：%s" % PATH)
	push_error("跑 python3 tools/skills_build.py 生成配置；本局先用内置默认数值。")
	_characters = {"default": _fallback()}


static func source_hash() -> String:
	_load()
	return _source_hash


static func slugs() -> Array:
	_load()
	return _characters.keys()


static func has_character(slug: String) -> bool:
	_load()
	return _characters.has(slug)


static func character(slug: String) -> Dictionary:
	_load()
	if _characters.has(slug):
		return _characters[slug]
	push_error("配置里没有角色 %s，用内置默认数值代替" % slug)
	return _fallback()


static func stats(slug: String) -> Dictionary:
	return character(slug).get("stats", {})


static func stat(slug: String, key: String, fallback: float) -> float:
	var value = stats(slug).get(key, fallback)
	return float(value) if value != null else fallback


static func moves(slug: String) -> Array:
	return character(slug).get("moves", [])


static func move(slug: String, id: String) -> Dictionary:
	for m in moves(slug):
		if String(m.get("id", "")) == id:
			return m
	return {}


static func slot_moves(slug: String, slot: String) -> Array:
	"""The moves bound to a skill slot, in order (basic is a chain)."""
	var ids: Array = character(slug).get("slots", {}).get(slot, [])
	var out: Array = []
	for id in ids:
		var m := move(slug, String(id))
		if not m.is_empty():
			out.append(m)
	return out


static func first_of(slug: String, slot: String) -> Dictionary:
	var list := slot_moves(slug, slot)
	return list[0] if not list.is_empty() else {}


static func seconds(frames: float) -> float:
	"""Frame counts are the designer-facing unit; the simulation runs in seconds."""
	return frames / FPS


static func _fallback() -> Dictionary:
	var stats := {
		"hp": 100.0, "energy_max": 100.0, "energy_start": 60.0,
		"energy_regen_per_sec": 2.5, "energy_on_hit": 8.0,
		"walk_speed": 330.0, "air_speed": 430.0, "jump_speed": -780.0,
		"fly_speed": -560.0, "fly_drain_per_sec": 22.0, "fastfall_speed": 1350.0,
		"hurtbox": {"w": 56.0, "h": 150.0},
	}
	var punch := {
		"id": "punch_1", "name": "直拳", "pose": "attack", "kind": "light", "hit_sfx": "hit_light",
		"startup_f": 5, "active_f": 5, "recovery_f": 8, "damage": 6.0,
		"hitbox": {"x": 22.0, "y": -108.0, "w": 72.0, "h": 78.0},
		"knockback": {"x": 220.0, "y": 0.0},
		"hitstun_f": 16, "blockstun_f": 12, "hitstop_f": 4,
		"cost": 0.0, "cooldown_f": 0, "air_ok": false,
		"impulse_x": 0.0, "impulse_y": 0.0, "lunge": 18.0,
		"cancel_from_f": 0, "cancel_to_f": 0, "cancel_into": [], "cancel_on": "any",
		"sfx": "whoosh_light", "voice": "attack_light",
		"ai": {"range": 80.0, "weight": 1.0},
	}
	var orb := {
		"id": "chakra_orb", "name": "忍术·气弹", "pose": "proj", "kind": "chakra", "hit_sfx": "chakra_hit",
		"startup_f": 5, "active_f": 4, "recovery_f": 7, "damage": 0.0,
		"hitbox": null, "knockback": {"x": 0.0, "y": 0.0},
		"hitstun_f": 0, "blockstun_f": 0, "hitstop_f": 0,
		"cost": 24.0, "cooldown_f": 0, "air_ok": true,
		"impulse_x": 0.0, "impulse_y": 0.0, "lunge": 14.0,
		"cancel_from_f": 0, "cancel_to_f": 0, "cancel_into": [], "cancel_on": "any",
		"sfx": "chakra_charge", "voice": "technique",
		"projectile": {
			"damage": 14.0, "speed": 760.0, "radius": 13.0, "life_f": 144,
			"knockback": {"x": 430.0, "y": -200.0},
			"hitstun_f": 16, "blockstun_f": 14, "hitstop_f": 6,
			"hit_kind": "chakra_hit", "color": [0.55, 0.9, 1.0],
			"spawn_sfx": "chakra_shoot", "hit_sfx": "chakra_hit", "death_sfx": "poof",
		},
		"ai": {"range": 900.0, "weight": 0.55},
	}
	return {
		"slug": "default", "display": "NINJA", "voice_pitch": 1.0, "stats": stats,
		"moves": [punch, orb],
		"slots": {"basic": ["punch_1"], "air": [], "skill_1": [], "skill_2": [], "jutsu": ["chakra_orb"]},
	}
