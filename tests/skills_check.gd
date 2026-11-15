extends SceneTree

# Skill pipeline check: a number a designer writes in data/skills/<slug>.json has
# to survive the whole trip
#
#     data/skills/*.json -> tools/skills_build.py -> data/characters.generated.json
#                        -> scripts/skill_db.gd -> the running Fighter
#
# and this test walks that trip from the live scene backwards. The failure it is
# really guarding against is the quiet one: the config file is missing, or stale,
# or names a move nobody can reach, and the game plays on with hardcoded
# fallbacks while the designer's edit appears to do nothing.
#
# Run headless:
#
#   godot --headless --path . -s res://tests/skills_check.gd
#
# Exits 0 and prints SKILLS OK, or exits 1 listing what is broken.

const SkillDb = preload("res://scripts/skill_db.gd")

# The slots a player can press and the CPU will consider. `basic` is the attack
# button's chain and `air` is the same button in the air, so every one of these
# has to have something in it or a key on the HUD does nothing.
const PLAYER_SLOTS := ["basic", "air", "skill_1", "skill_2", "jutsu"]

# The CPU picks between moves with the global RNG, so the live half of this test
# pins the seed: a failure then means the config or the AI changed, not that the
# dice went differently. Pass a different one with `-- <n>`.
const MATCH_SEED := 7

var _main = null
var _frames := 0
var _failures: Array[String] = []
var _checks := 0
var _started := false
var _sampling := false
var _used_slots := {}


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	seed(int(args[0]) if args.size() > 0 else MATCH_SEED)
	change_scene_to_file("res://scenes/main.tscn")
	process_frame.connect(_tick)


func _tick() -> void:
	if _main == null:
		_main = root.get_node_or_null("Main")
		if _main != null:
			_main._start_match("sora", "kaze")
		return
	_frames += 1
	if _frames < 3 or _main.fighters.size() < 2:
		return
	if not _started:
		_started = true
		_run()
		# Then let a real CPU match play out, sampling which slots the fighters
		# actually end up in. The config can be wired correctly and still be
		# AI-dead (every ai.range too short, every weight zero), and that is the
		# difference between "the table loads" and "the fight uses the table".
		for f in _main.fighters:
			f.is_ai = true
		# Re-seed here, not just in _initialize: Main._ready() calls randomize()
		# to give each real match its own flavour, which would otherwise throw
		# away the seed set above. Cosmetic code no longer draws from the global
		# generator (see _update_shake / Bg._rng), so from this point the fight -
		# and therefore which slots get used - is a pure function of the seed.
		seed(MATCH_SEED)
		_sampling = true
		return
	if not _sampling:
		return
	for f in _main.fighters:
		if f.state == f.State.ATTACK and String(f._move_slot) != "":
			_used_slots[String(f._move_slot)] = int(_used_slots.get(String(f._move_slot), 0)) + 1
	if _frames < 3000 and _main.phase != "over":
		return
	_check(_used_slots.has("skill_1") or _used_slots.has("skill_2"),
		"CPU 在一整局里真的用了配置的技能槽（不是只会打基本连段）",
		"实际用到：%s" % [", ".join(_used_slots.keys())])
	_report()
	quit(0 if _failures.is_empty() else 1)


func _run() -> void:
	_own_check()
	_live_check()
	_facing_check()
	# Last, because these two deliberately overwrite the fighters' live state
	# (energy, buffers, position) to drive the code paths under test.
	_window_check()
	_ai_window_check()


# ------------------------------------------------------- config -> runtime

# Everything else is meaningless if the game booted on the built-in fallback.
func _own_check() -> void:
	_check(SkillDb.source_hash() != "", "data/characters.generated.json 被真的加载了（不是内置兜底）",
		"跑 python3 tools/skills_build.py 生成配置")
	var slugs := SkillDb.slugs()
	_check(slugs.size() >= 2, "配置里有多个角色", "现在只有 %d 个" % slugs.size())

	for slug in slugs:
		var stats := SkillDb.stats(slug)
		_check(not stats.is_empty(), "%s：stats 非空" % slug)
		var slots: Dictionary = SkillDb.character(slug).get("slots", {})
		for slot in PLAYER_SLOTS:
			_check(slots.has(slot), "%s：配置里写了 %s 槽" % [slug, slot])
			var list: Array = slots.get(slot, [])
			_check(not list.is_empty(), "%s：%s 槽不是空的（玩家按键/CPU 会用到）" % [slug, slot],
				"空槽＝这个键按下去没反应")
			for mid in list:
				var m := SkillDb.move(slug, String(mid))
				_check(not m.is_empty(), "%s：%s 槽的 %s 能在 moves 里找到" % [slug, slot, mid])

		# The build tool writes frame_advantage into the generated file, which is
		# what the designer-facing table is printed from. If the two ever disagree
		# the table is lying, so recompute it here from the raw frame data.
		for m in SkillDb.moves(slug):
			var remaining := int(m.get("active_f", 1)) - 1 + int(m.get("recovery_f", 0))
			var fa: Dictionary = m.get("frame_advantage", {})
			_check(int(fa.get("on_hit", 0)) == int(m.get("hitstun_f", 0)) - remaining,
				"%s.%s：写入的命中帧优势等于 hitstun - 剩余收招帧" % [slug, m.get("id", "")])
			_check(int(fa.get("on_block", 0)) == int(m.get("blockstun_f", 0)) - remaining,
				"%s.%s：写入的防御帧优势等于 blockstun - 剩余收招帧" % [slug, m.get("id", "")])


# ------------------------------------------------------- button -> move

# Pressing a key has to select the move the config put in that slot. This is the
# hop where a renamed slot or a typo'd id turns into "the button does nothing".
func _window_check() -> void:
	for f in _main.fighters:
		var slug: String = f.art_slug
		for slot in ["jutsu", "skill_1", "skill_2"]:
			_expect_move(f, slug, slot)
			_expect_move(f, slug, "basic")
		_expect_move(f, slug, "air", true)


func _expect_move(f, slug: String, slot: String, in_air := false) -> void:
	var want := SkillDb.first_of(slug, slot)
	if want.is_empty():
		return
	f.state = f.State.IDLE
	f.grounded = not in_air
	f.energy = SkillDb.stat(slug, "energy_max", 100.0)
	f._cooldown.clear()
	for s in SkillDb.SLOTS:
		f._buf[s] = 0
	f._buf[slot] = 8
	var got: Dictionary = f._pick_buffered_move(in_air)
	_check(String(got.get("id", "")) == String(want.get("id", "")),
		"%s：按 %s 会出 %s" % [slug, slot, want.get("id", "")],
		"实际出了 %s" % String(got.get("id", "<空>")))


# ------------------------------------------------------- geometry in game

func _live_check() -> void:
	for f in _main.fighters:
		var slug: String = f.art_slug
		var stats := SkillDb.stats(slug)
		_check(not f.def.is_empty() and String(f.def.get("slug", "")) == slug,
			"%s：场上的角色用的是配置里的 def" % slug)
		_check(is_equal_approx(f.max_hp, float(stats.get("hp", -1.0))),
			"%s：开局血量来自配置 hp" % slug, "配置 %s / 实际 %s" % [stats.get("hp"), f.max_hp])
		# Energy regenerates from the very first simulated frame, so this is a
		# window rather than an equality: at least the configured start value and
		# not more than a second of regen above it.
		var start := float(stats.get("energy_start", -1.0))
		_check(f.energy >= start - 0.001 and f.energy <= start + float(stats.get("energy_regen_per_sec", 0.0)),
			"%s：开局气量来自配置 energy_start" % slug, "配置 %s / 实际 %.2f" % [start, f.energy])

		# The hitbox is authored in body space and mirrored by the game; check the
		# mirroring against the numbers instead of trusting the drawing.
		var m := SkillDb.move(slug, "dash_strike")
		if m.is_empty():
			continue
		var box: Dictionary = m.get("hitbox", {})
		var w := float(box.get("w", 0.0))
		var h := float(box.get("h", 0.0))
		f._move = m
		f.position = Vector2(400.0, 600.0)
		f.facing = 1
		var right: Rect2 = f.melee_rect()
		f.facing = -1
		var left: Rect2 = f.melee_rect()
		_check(right.size == Vector2(w, h), "%s：判定框尺寸来自配置" % slug)
		_check(is_equal_approx(right.position.x, 400.0 + float(box.get("x", 0.0))),
			"%s：面朝右时判定框朝 +X 伸出" % slug)
		_check(is_equal_approx(left.position.x, 400.0 - (float(box.get("x", 0.0)) + w)),
			"%s：面朝左时判定框镜像" % slug)
		f._move = {}


# ------------------------------------------------------- auto facing

# The cast auto-faces: no key for it, whoever is behind turns around. It has to
# stop during a move, though, or a cross-up would spin the attacker mid-swing.
func _facing_check() -> void:
	var a = _main.fighters[0]
	var b = _main.fighters[1]
	a.state = a.State.IDLE
	b.state = b.State.IDLE
	a.position = Vector2(400.0, 600.0)
	b.position = Vector2(900.0, 600.0)
	a.facing = -1
	b.facing = 1
	a._update_facing()
	b._update_facing()
	_check(a.facing == 1 and b.facing == -1, "自动朝向：两人面对面时各朝对方")

	a.position = Vector2(900.0, 600.0)
	b.position = Vector2(400.0, 600.0)
	a._update_facing()
	b._update_facing()
	_check(a.facing == -1 and b.facing == 1, "自动朝向：跳过对手后自动转身")

	a.state = a.State.ATTACK
	a.facing = 1
	a.position = Vector2(900.0, 600.0)
	b.position = Vector2(400.0, 600.0)
	a._update_facing()
	_check(a.facing == 1, "自动朝向：出招中锁定朝向，不会挥到一半转身")
	a.state = a.State.IDLE


# ------------------------------------------------------- AI reads the config

# The CPU picks its skills from ai.range / ai.min_range / ai.weight. These check
# the window is respected, because "the designer raised the weight and nothing
# happened" is the failure mode this whole layer exists to prevent.
func _ai_window_check() -> void:
	for f in _main.fighters:
		f.energy = SkillDb.stat(f.art_slug, "energy_max", 100.0)
		f._cooldown.clear()
		_check(f._ai_pick_slot(1300.0) == "", "%s：超出所有招式的 ai.range 时 CPU 不出技能" % f.art_slug)
		for dist in [40.0, 300.0, 700.0]:
			var slot: String = f._ai_pick_slot(dist)
			if slot == "":
				continue
			var ai: Dictionary = SkillDb.first_of(f.art_slug, slot).get("ai", {})
			_check(dist <= float(ai.get("range", 0.0)) and dist >= float(ai.get("min_range", 0.0)),
				"%s：CPU 在 %s 距离选中的 %s 在它的 ai 窗口内" % [f.art_slug, dist, slot],
				"窗口是 %s~%s" % [ai.get("min_range", 0.0), ai.get("range", 0.0)])


# --------------------------------------------------------------- plumbing

func _check(ok: bool, label: String, detail := "") -> void:
	_checks += 1
	if ok:
		return
	_failures.append(label + ("（" + detail + "）" if detail != "" else ""))


func _report() -> void:
	if _failures.is_empty():
		print("SKILLS OK: %d checks passed" % _checks)
		return
	print("SKILLS FAIL: %d of %d checks failed" % [_failures.size(), _checks])
	for f in _failures:
		print("  - ", f)
