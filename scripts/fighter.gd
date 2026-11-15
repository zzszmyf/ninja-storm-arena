class_name Fighter
extends Node2D

const SkillDb = preload("res://scripts/skill_db.gd")

# A hand-rolled, readable state machine for an aerial fighting game.
# States: IDLE / RUN / AIR / ATTACK / HURT / BLOCK / KO
#
# This file knows *how* to run a move and nothing about which moves exist.
# Startup/active/recovery, hitboxes, hitstun, knockback and cancel windows all
# come from `move`, the dictionary handed over by the character def that
# SkillDb loaded. Adding a move is a config edit, not a code edit.
enum State { IDLE, RUN, AIR, ATTACK, HURT, BLOCK, KO }

# Fallbacks, used only when a character def leaves a field out.
const GRAVITY := 1900.0
const TERMINAL_VEL := 1500.0
const GROUND_ACCEL := 2400.0
const AIR_ACCEL := 2300.0
const FRICTION := 2200.0
const MAX_GROUND_SPEED := 330.0
const MAX_AIR_SPEED := 430.0
const JUMP_SPEED := -780.0
const FLY_SPEED := -560.0
const FLY_DRAIN := 22.0
const FASTFALL_SPEED := 1350.0
const ENERGY_REGEN := 2.5
const ENERGY_HIT_GAIN := 8.0
const BODY_W := 56.0
const BODY_H := 150.0
# Blocked hits only chip, instead of the full damage a frame-data game would
# need to compensate for blockstun some other way.
const BLOCK_CHIP := 0.12
const BUFFER_FRAMES := 8
const SUBSTITUTE_COST := 28.0
const SUBSTITUTE_COOLDOWN_FRAMES := 180
const SUBSTITUTE_INVULN_FRAMES := 12

@export var player_id := 1

var display_name := "NINJA"
var art_slug := "sora"
var is_ai := false
var voice_pitch := 1.0  # per-character timbre offset for the voice barks
var def: Dictionary = {}  # character def from SkillDb: stats + moves + slots
var main  # untyped: Arena main scene root
var opponent: Fighter = null

var max_hp := 100.0
var hp := 100.0
var energy := 60.0

var state := State.IDLE
var grounded := true
var facing := 1
var velocity := Vector2.ZERO

var ground_y := 600.0
var arena_min_x := 70.0
var arena_max_x := 1210.0

# Move execution. `_move` is the config dict of whatever is running right now;
# everything below is bookkeeping about *where inside that move* we are.
var _move: Dictionary = {}
var _move_slot := ""
var _atk_frame := 0
var _atk_hit := false
var _atk_blocked := false

var _cooldown: Dictionary = {}  # move id -> physics frames left
var _buf: Dictionary = {}  # slot name -> physics frames left

var _proj_spawned := false

# Hurt / KO
var _hurt_frame := 0
var _hurt_was_air := false
var _ko_t := 0.0
var _hit_flash := 0.0
var air_hits := 0
var _block_stun := 0
var _substitute_cooldown := 0
var _substitute_invuln := 0

# Input buffer (frames)
var _buf_jump := 0

var _anim_t := 0.0
var _flying := false
var _ghosts: Array = []
var _ghost_t := 0.0
var _poof_cd := 0.0
var _fastfall_cd := 0.0

# AI intentions
var _ai_dir := 0.0
var _ai_jump_hold := false
var _ai_descend := false
var _ai_jump_press := false
var _ai_melee := false
var _ai_proj := false
var _ai_skill := ""
var _ai_think := 0.0
var _ai_cooldown := 0.0
var _ai_cast_timer := 0.0


func _init() -> void:
	for slot in SkillDb.SLOTS:
		_buf[slot] = 0


func _physics_process(delta: float) -> void:
	if main == null or main.frozen():
		return
	if not main.round_started:
		queue_redraw()
		return

	_tick_buffers()
	_substitute_cooldown = maxi(0, _substitute_cooldown - 1)
	_substitute_invuln = maxi(0, _substitute_invuln - 1)
	_update_facing()
	if is_ai:
		_ai_update(delta)
	var intent := _collect_intent()
	_apply_intent_to_buffers(intent)
	if state == State.HURT and intent.get("substitute", false) and _try_substitute():
		_apply_motion_and_limits(delta)
		_separate_from_opponent()
		_anim_t += delta
		_update_ghosts(delta)
		queue_redraw()
		return

	_hit_flash = maxf(0.0, _hit_flash - delta)
	_fastfall_cd = maxf(0.0, _fastfall_cd - delta)
	if state != State.KO:
		energy = minf(_stat("energy_max", 100.0), energy + _stat("energy_regen_per_sec", ENERGY_REGEN) * delta)

	match state:
		State.IDLE, State.RUN:
			_state_ground(delta, intent)
		State.AIR:
			_state_air(delta, intent)
		State.ATTACK:
			_state_attack(delta)
		State.HURT:
			_state_hurt(delta)
		State.BLOCK:
			_state_block(delta, intent)
		State.KO:
			_state_ko(delta)

	_apply_motion_and_limits(delta)
	_separate_from_opponent()
	_anim_t += delta
	_update_ghosts(delta)
	queue_redraw()


# ------------------------------------------------------------------ ground

func _state_ground(delta: float, intent: Dictionary) -> void:
	if intent.block:
		velocity.x = 0.0
		state = State.BLOCK
		return

	var dir: float = intent.dir
	if dir != 0.0:
		velocity.x = move_toward(velocity.x, dir * _stat("walk_speed", MAX_GROUND_SPEED), GROUND_ACCEL * delta)
		state = State.RUN
	else:
		velocity.x = move_toward(velocity.x, 0.0, FRICTION * delta)
		state = State.IDLE if absf(velocity.x) < 10.0 else State.RUN

	if _buf_jump > 0:
		_buf_jump = 0
		_do_jump()
		return
	var m := _pick_buffered_move(false)
	if not m.is_empty():
		_start_move(m)


# ------------------------------------------------------------------- air

func _state_air(delta: float, intent: Dictionary) -> void:
	var was_flying := _flying
	var was_fastfall := velocity.y > FASTFALL_SPEED * 0.5
	if intent.block:
		velocity.y = move_toward(velocity.y, _stat("fastfall_speed", FASTFALL_SPEED), 3200.0 * delta)
		_flying = false
		# One whoosh per dive, not one per key tap: holding the drop key would
		# otherwise re-trigger the swell every time the ramp crosses threshold.
		if not was_fastfall and _fastfall_cd <= 0.0:
			_fastfall_cd = 0.45
			_sound("whoosh_heavy", -6.0)
	elif intent.jump_hold and energy > 0.5:
		velocity.y = move_toward(velocity.y, _stat("fly_speed", FLY_SPEED), 1500.0 * delta)
		energy = maxf(0.0, energy - _stat("fly_drain_per_sec", FLY_DRAIN) * delta)
		_flying = true
	else:
		velocity.y = minf(velocity.y + GRAVITY * delta, TERMINAL_VEL)
		_flying = false
	# Kicking in the chakra thrust is a distinct event worth hearing once.
	if _flying and not was_flying:
		_sound("dash", -2.0)

	var dir: float = intent.dir
	if dir != 0.0:
		velocity.x = move_toward(velocity.x, dir * _stat("air_speed", MAX_AIR_SPEED), AIR_ACCEL * delta)
	else:
		velocity.x = move_toward(velocity.x, 0.0, 520.0 * delta)

	var m := _pick_buffered_move(true)
	if not m.is_empty():
		_start_move(m)


func _do_jump() -> void:
	grounded = false
	velocity.y = _stat("jump_speed", JUMP_SPEED)
	state = State.AIR
	_sound("jump")


# --------------------------------------------------------------- moves

func _start_move(m: Dictionary) -> void:
	_move = m
	_move_slot = _slot_of_move(String(m.get("id", "")))
	_atk_frame = 0
	_atk_hit = false
	_atk_blocked = false
	_proj_spawned = false
	state = State.ATTACK

	var cost := float(m.get("cost", 0.0))
	if cost > 0.0:
		energy = maxf(0.0, energy - cost)
	var cd := int(m.get("cooldown_f", 0))
	if cd > 0:
		_cooldown[String(m.get("id", ""))] = cd

	var ix := float(m.get("impulse_x", 0.0))
	var iy := float(m.get("impulse_y", 0.0))
	if grounded:
		velocity.x = facing * ix
		velocity.y = iy
	else:
		if ix != 0.0:
			velocity.x = facing * ix
		if iy != 0.0:
			# An air move may lift us, never cut a faster climb short.
			velocity.y = minf(velocity.y, iy)

	var whoosh := String(m.get("sfx", ""))
	if not whoosh.is_empty():
		_sound(whoosh, -1.5)
	var line := String(m.get("voice", ""))
	if not line.is_empty():
		_say(line)


func _state_attack(delta: float) -> void:
	_atk_frame += 1
	var startup := int(_move.get("startup_f", 1))
	var active := int(_move.get("active_f", 1))
	var total := _move_length(_move)
	var active_end := startup + active

	if not grounded:
		velocity.y += GRAVITY * delta * 0.6
		velocity.y = minf(velocity.y, TERMINAL_VEL)

	# The projectile leaves the hand on the first active frame.
	if not _proj_spawned and _atk_frame >= startup and _move.get("projectile") != null:
		_proj_spawned = true
		if main != null:
			main.spawn_orb(self, _move)

	if _atk_frame >= startup and _atk_frame < active_end and not _atk_hit:
		_try_melee_hit()

	# Cancel windows are what turn "press attack three times" into a real string,
	# and they come from the config: cancel_into + the frame window it is live in.
	var nxt := _buffered_cancel()
	if not nxt.is_empty():
		_start_move(nxt)
		return

	if _atk_frame >= total:
		state = State.IDLE if grounded else State.AIR


func _try_melee_hit() -> void:
	if opponent == null or _move.is_empty():
		return
	if _move.get("hitbox") == null:
		return
	var my_rect := melee_rect()
	if not my_rect.intersects(opponent.hurt_rect()):
		return
	_atk_hit = true
	var kb: Dictionary = _move.get("knockback", {})
	opponent.take_hit(
		float(_move.get("damage", 0.0)),
		Vector2(facing * float(kb.get("x", 0.0)), float(kb.get("y", 0.0))),
		my_rect.get_center(),
		self,
		String(_move.get("hit_sfx", "hit_light")),
		int(_move.get("hitstun_f", 15)),
		int(_move.get("blockstun_f", 10)),
		int(_move.get("hitstop_f", -1)),
		_move.get("fx_color"),
	)


func _buffered_cancel() -> Dictionary:
	if _move.is_empty():
		return {}
	var to := int(_move.get("cancel_to_f", 0))
	if to <= 0 or _atk_frame < int(_move.get("cancel_from_f", 0)) or _atk_frame > to:
		return {}
	var on := String(_move.get("cancel_on", "any"))
	if on == "hit" and not _atk_hit:
		return {}
	if on == "block" and not _atk_blocked:
		return {}
	for target in _move.get("cancel_into", []):
		var slot := _slot_of_move(String(target))
		if slot.is_empty() or int(_buf.get(slot, 0)) <= 0:
			continue
		var m := SkillDb.move(art_slug, String(target))
		if not m.is_empty() and _can_cast(m):
			_buf[slot] = 0
			return m
	return {}


# ----------------------------------------------------------------- hurt

func take_hit(dmg: float, kb: Vector2, hit_pos: Vector2, attacker, kind := "",
		hitstun_f := 15, blockstun_f := 10, hitstop_f := -1, impact_color: Variant = null) -> void:
	if state == State.KO or _substitute_invuln > 0:
		return
	if state == State.BLOCK:
		hp = maxf(0.0, hp - dmg * BLOCK_CHIP)
		_hit_flash = 0.10
		velocity = Vector2(facing * -160.0, 0.0)
		# Blockstun is what makes guarding cost something. Without it the
		# defender can act on the very frame the hit lands, and "frame advantage
		# on block" is not a thing that exists.
		_block_stun = maxi(_block_stun, blockstun_f)
		if attacker != null:
			attacker._atk_blocked = true
		if main != null:
			main.on_blocked(self, attacker, hit_pos)
		if hp <= 0.0:
			_start_ko(Vector2(facing * -420.0, -260.0))
		return

	hp -= dmg
	_hit_flash = 0.13
	if hp <= 0.0:
		_start_ko(kb)
		return

	if kind != "chakra_hit":
		_say("hurt")
	_hurt_was_air = not grounded
	if _hurt_was_air:
		air_hits += 1
	state = State.HURT
	_hurt_frame = maxi(1, hitstun_f)
	velocity = kb
	# Hits with upward knockback lift the victim off the ground. This must
	# clear the grounded flag or the fighter would drift through the air
	# while still being simulated as standing.
	if kb.y < 0.0:
		grounded = false
	if attacker != null:
		attacker.energy = minf(_stat("energy_max", 100.0), attacker.energy + _stat("energy_on_hit", ENERGY_HIT_GAIN))
	if main != null:
		main.on_hit_landed(self, attacker, hit_pos, dmg, _hurt_was_air, kind, hitstop_f, impact_color)


func _try_substitute() -> bool:
	if opponent == null or opponent.state == State.KO:
		return false
	if _substitute_cooldown > 0 or energy < SUBSTITUTE_COST:
		return false
	var old_pos := position
	var side := -1.0 if position.x > opponent.position.x else 1.0
	position.x = clampf(opponent.position.x + side * 88.0, arena_min_x, arena_max_x)
	position.y = maxf(ground_y - 150.0, opponent.position.y - 30.0) if not grounded else ground_y
	energy -= SUBSTITUTE_COST
	_substitute_cooldown = SUBSTITUTE_COOLDOWN_FRAMES
	_substitute_invuln = SUBSTITUTE_INVULN_FRAMES
	_hurt_frame = 0
	velocity = Vector2.ZERO
	grounded = position.y >= ground_y
	state = State.IDLE if grounded else State.AIR
	_hit_flash = 0.08
	if main != null:
		main.spawn_fx(old_pos + Vector2(0, -76), Color(0.72, 0.78, 0.9), 42.0)
		main.spawn_fx(position + Vector2(0, -76), Color(0.72, 0.78, 0.9), 32.0)
		main.sfx.play_at("poof", old_pos + Vector2(0, -76))
	return true


func _state_hurt(delta: float) -> void:
	_hurt_frame -= 1
	if not grounded:
		velocity.y += GRAVITY * delta * 0.85
		velocity.y = minf(velocity.y, TERMINAL_VEL)
	velocity.x = move_toward(velocity.x, 0.0, 1500.0 * delta)
	if _hurt_frame <= 0:
		state = State.IDLE if grounded else State.AIR


func _start_ko(kb: Vector2) -> void:
	state = State.KO
	_ko_t = 0.0
	velocity = kb
	_say("ko")
	if main != null:
		main.on_ko(self)


func _state_ko(delta: float) -> void:
	_ko_t += delta
	velocity.y = minf(velocity.y + GRAVITY * delta * 0.9, 1200.0)
	velocity.x = move_toward(velocity.x, 0.0, 500.0 * delta)


# ---------------------------------------------------------------- block

func _state_block(delta: float, intent: Dictionary) -> void:
	velocity.x = 0.0
	if _block_stun > 0:
		_block_stun -= 1
		return
	if not intent.block:
		state = State.IDLE
		return
	var m := _pick_buffered_move(false)
	if not m.is_empty():
		_start_move(m)


# ------------------------------------------------------------------ AI

func _ai_update(delta: float) -> void:
	_ai_cooldown = maxf(0.0, _ai_cooldown - delta)
	_ai_cast_timer += delta
	# Only the one-shot actions are cleared every frame. The movement plan is
	# held until the next think tick: wiping it each frame (what this used to
	# do) meant the CPU accelerated for a single frame out of eight, so it
	# never closed the gap and spent the whole round firing orbs from range.
	_ai_jump_press = false
	_ai_melee = false
	_ai_proj = false
	_ai_skill = ""
	if state in [State.HURT, State.KO]:
		return
	if state == State.ATTACK:
		# Keep pressing inside the cancel window: that buffer is what chains the
		# string, so without it the CPU only ever throws one jab. The window is
		# read from the move, not guessed from a step index.
		if not _move.is_empty() and int(_move.get("cancel_to_f", 0)) > 0 \
				and _atk_frame >= int(_move.get("cancel_from_f", 0)):
			if opponent != null and absf(opponent.position.x - position.x) < _move_reach() + 34.0:
				_ai_melee = true
		return

	if opponent == null:
		return
	var dx := opponent.position.x - position.x
	var dy := opponent.position.y - position.y
	var dist := absf(dx)
	var toward := 1.0 if dx > 0.0 else -1.0
	if dx == 0.0:
		toward = -facing

	if not grounded:
		# Air control is cheap to recompute, so it does not wait for a tick.
		_ai_dir = toward if dist > 190.0 else 0.0
		_ai_jump_hold = dy < -40.0 and energy > 12.0
		_ai_descend = dy > 40.0
		if dist < 150.0 and absf(dy) < 90.0 and randf() < 0.25:
			_ai_melee = true
		return

	_ai_think -= delta
	if _ai_think > 0.0:
		return

	# Plan from scratch, then hold it until the next tick.
	var enemy_busy := opponent.state == State.ATTACK
	_ai_dir = 0.0
	_ai_jump_hold = false
	_ai_descend = false
	var cast_ready := _ai_cooldown <= 0.0
	if dist > 520.0:
		_ai_think = 0.10 + randf() * 0.14
		_ai_dir = toward
		if cast_ready and randf() < 0.55:
			_ai_cast(dist)
	elif dist > 220.0:
		_ai_think = 0.10 + randf() * 0.14
		var roll := randf()
		if roll < 0.22:
			# Leap in. The arena is an aerial fighter, so the CPU uses the air.
			_ai_jump_press = true
			_ai_jump_hold = true
			_ai_dir = toward
		elif cast_ready and (roll > 0.72 or _ai_cast_timer > 3.5):
			# Occasionally, and always after a long quiet spell, hold the mid
			# range and use whatever the config says reaches this far.
			_ai_cast(dist)
		else:
			_ai_dir = toward
	elif enemy_busy and randf() < 0.45:
		# Guard the incoming attack instead of walking into it.
		_ai_think = 0.10 + randf() * 0.10
		_ai_descend = true
	else:
		# At swing range the CPU re-plans quickly, which is what lets it chain
		# the three-hit ground combo instead of dropping out of recovery.
		_ai_think = 0.05 + randf() * 0.06
		if dist > 120.0:
			_ai_dir = toward
		elif cast_ready and randf() < 0.20 and _ai_cast(dist):
			pass  # committed to a skill this tick, nothing else to decide
		elif randf() < 0.86:
			_ai_melee = true
		else:
			_ai_dir = -toward


func _ai_cast(dist: float) -> bool:
	"""Fire whichever configured skill the CPU's dice picked for this distance.

	The choice is pure config: `ai.range` is how far the move is worth using from
	and `ai.weight` is how often a designer wants it picked. Nothing here knows
	that "jutsu" is a fireball - it just presses that button.
	"""
	var slot := _ai_pick_slot(dist)
	if slot.is_empty():
		return false
	match slot:
		"jutsu":
			_ai_proj = true
		_:
			_ai_skill = slot
	var m := SkillDb.first_of(art_slug, slot)
	# Lock out for most of the move's own duration so the CPU commits to what it
	# threw instead of cancelling everything into everything.
	_ai_cooldown = maxf(0.25, float(_move_length(m)) / SkillDb.FPS * 0.9)
	_ai_cast_timer = 0.0
	return true


func _ai_pick_slot(dist: float) -> String:
	"""Weighted pick among the skill slots whose config reaches `dist`."""
	var total := 0.0
	var options: Array = []
	for slot in SkillDb.AI_SLOTS:
		var m := SkillDb.first_of(art_slug, slot)
		if m.is_empty() or not _can_cast(m):
			continue
		var ai: Dictionary = m.get("ai", {})
		# `range` is the far edge, `min_range` (optional, default 0) the near one.
		if dist > float(ai.get("range", 0.0)) or dist < float(ai.get("min_range", 0.0)):
			continue
		total += maxf(0.0, float(ai.get("weight", 0.0)))
		options.append({"slot": slot, "acc": total})
	if options.is_empty() or total <= 0.0:
		return ""
	var roll := randf() * total
	for o in options:
		if roll <= float(o["acc"]):
			return String(o["slot"])
	return String(options[-1]["slot"])


# -------------------------------------------------------------- helpers

func _tick_buffers() -> void:
	_buf_jump = maxi(0, _buf_jump - 1)
	for slot in _buf.keys():
		_buf[slot] = maxi(0, int(_buf[slot]) - 1)
	for id in _cooldown.keys():
		_cooldown[id] = maxi(0, int(_cooldown[id]) - 1)


func _collect_intent() -> Dictionary:
	if is_ai:
		return {
			"dir": _ai_dir,
			"jump_hold": _ai_jump_hold,
			"jump_press": _ai_jump_press,
			"block": _ai_descend,
			"melee": _ai_melee,
			"proj": _ai_proj,
			"skill_1": _ai_skill == "skill_1",
		"skill_2": _ai_skill == "skill_2",
		"ultimate": false,
		"substitute": false,
		}
	var id := player_id
	return {
		"dir": Input.get_action_strength("p%d_right" % id) - Input.get_action_strength("p%d_left" % id),
		"jump_hold": Input.is_action_pressed("p%d_jump" % id),
		"jump_press": Input.is_action_just_pressed("p%d_jump" % id),
		"block": Input.is_action_pressed("p%d_block" % id),
		"melee": Input.is_action_just_pressed("p%d_melee" % id),
		"proj": Input.is_action_just_pressed("p%d_proj" % id),
		"skill_1": Input.is_action_just_pressed("p%d_skill1" % id),
		"skill_2": Input.is_action_just_pressed("p%d_skill2" % id),
		"ultimate": Input.is_action_just_pressed("p%d_ultimate" % id),
		"substitute": Input.is_action_just_pressed("p%d_substitute" % id),
	}


func _apply_intent_to_buffers(intent: Dictionary) -> void:
	if intent.jump_press:
		_buf_jump = BUFFER_FRAMES
	if intent.melee:
		# The attack button means "next link of the basic string" on the ground
		# and "the air move" in the air, so it feeds whichever slot is live.
		_buf["basic" if grounded else "air"] = BUFFER_FRAMES
	if intent.proj:
		_buf["jutsu"] = BUFFER_FRAMES
	if intent.get("skill_1", false):
		_buf["skill_1"] = BUFFER_FRAMES
	if intent.get("skill_2", false):
		_buf["skill_2"] = BUFFER_FRAMES
	if intent.get("ultimate", false):
		_buf["ultimate"] = BUFFER_FRAMES


# ------------------------------------------------------------ move lookup

func _stat(key: String, fallback: float) -> float:
	if def.is_empty():
		return fallback
	var value = def.get("stats", {}).get(key, fallback)
	return float(value) if value != null else fallback


func _move_length(m: Dictionary) -> int:
	return int(m.get("startup_f", 0)) + int(m.get("active_f", 0)) + int(m.get("recovery_f", 0))


func _can_cast(m: Dictionary) -> bool:
	if m.is_empty():
		return false
	if int(_cooldown.get(String(m.get("id", "")), 0)) > 0:
		return false
	return energy >= float(m.get("cost", 0.0))


func _slot_of_move(id: String) -> String:
	if def.is_empty():
		return ""
	var slots: Dictionary = def.get("slots", {})
	for slot in SkillDb.SLOTS:
		if id in slots.get(slot, []):
			return slot
	return ""


func _pick_buffered_move(in_air: bool) -> Dictionary:
	# Jutsu first, then the numbered skills, then the basic string: pressing two
	# buttons on the same frame should favour the deliberate one.
	var order := ["ultimate", "jutsu", "skill_2", "skill_1"]
	order.append("air" if in_air else "basic")
	for slot in order:
		if int(_buf.get(slot, 0)) <= 0:
			continue
		var m := SkillDb.first_of(art_slug, slot)
		if m.is_empty():
			continue
		if in_air and slot != "air" and not bool(m.get("air_ok", false)):
			continue
		if not _can_cast(m):
			continue
		_buf[slot] = 0
		return m
	return {}


func _move_reach() -> float:
	if _move.is_empty() or _move.get("hitbox") == null:
		return 60.0
	var box: Dictionary = _move["hitbox"]
	return float(box.get("x", 0.0)) + float(box.get("w", 0.0))


func _update_facing() -> void:
	if state in [State.ATTACK, State.KO] or opponent == null:
		return
	if opponent.position.x == position.x:
		return
	facing = 1 if opponent.position.x > position.x else -1


func _apply_motion_and_limits(delta: float) -> void:
	position += velocity * delta
	if position.x < arena_min_x:
		position.x = arena_min_x
		if velocity.x < 0.0:
			velocity.x = 0.0
	elif position.x > arena_max_x:
		position.x = arena_max_x
		if velocity.x > 0.0:
			velocity.x = 0.0
	if position.y < 90.0:
		position.y = 90.0
		if velocity.y < 0.0:
			velocity.y = 0.0
	if position.y >= ground_y:
		position.y = ground_y
		if not grounded:
			grounded = true
			# Land harder after a long drop: the fast-fall move is the loud one.
			_sound("land", -4.0 if velocity.y > FASTFALL_SPEED * 0.5 else 0.0)
			velocity.y = 0.0
			match state:
				State.AIR:
					state = State.IDLE
				_:
					pass


func _separate_from_opponent() -> void:
	if opponent == null or state == State.KO or opponent.state == State.KO:
		return
	var dx := opponent.position.x - position.x
	if absf(dx) >= BODY_W:
		return
	if absf(opponent.position.y - position.y) > 130.0:
		return
	var dir := 1.0 if dx > 0.0 else -1.0
	if dx == 0.0:
		dir = -facing
	var gap := BODY_W - absf(dx)
	var shift := gap * 0.5
	position.x = clampf(position.x - dir * shift, arena_min_x, arena_max_x)


# ------------------------------------------------------------- geometry

func hurt_rect() -> Rect2:
	var box := _hurtbox()
	return Rect2(position.x - box.x * 0.5, position.y - box.y, box.x, box.y)


func _hurtbox() -> Vector2:
	# Hurtboxes are deliberately tunable on their own: making one bigger than
	# the artwork is the standard way to make a move easier to punish.
	if not def.is_empty():
		var box = def.get("stats", {}).get("hurtbox")
		if box is Dictionary and box.has("w") and box.has("h"):
			return Vector2(float(box["w"]), float(box["h"]))
	return Vector2(BODY_W, BODY_H)


func melee_rect() -> Rect2:
	# The hitbox is authored in body space: origin at the feet, +X towards the
	# way the fighter faces, Y negative going up. Mirroring it for a fighter
	# facing left is the only thing this function does with geometry.
	var box: Dictionary = _move.get("hitbox", {}) if not _move.is_empty() else {}
	if box.is_empty():
		return Rect2()
	var w := float(box.get("w", 0.0))
	var h := float(box.get("h", 0.0))
	var x := float(box.get("x", 0.0))
	var y := float(box.get("y", 0.0))
	var left := position.x + (x if facing > 0 else -(x + w))
	return Rect2(left, position.y + y, w, h)


# ---------------------------------------------------------------- draw

func _draw() -> void:
	# Ground shadow: squashed ellipse that fades as the fighter gains altitude.
	var shadow_y: float = ground_y - position.y
	var alt: float = clampf(1.0 - shadow_y / 700.0, 0.25, 1.0)
	draw_set_transform(Vector2(0.0, shadow_y), 0.0, Vector2(1.0, 0.22))
	draw_circle(Vector2.ZERO, 12.0 + 30.0 * alt, Color(0.0, 0.0, 0.0, 0.32 * alt))
	draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)

	var pal := _palette()
	var accent: Color = pal["accent"]
	var pose := _art_pose()
	var info := Art.pose_info(art_slug, pose)
	var tex: Texture2D = Art.pose_texture(art_slug, pose)

	# Anime afterimages trailing fast movement.
	for g in _ghosts:
		var ghost: Dictionary = g
		var g_pose: String = ghost["pose"]
		var g_info := Art.pose_info(art_slug, g_pose)
		var g_tex: Texture2D = Art.pose_texture(art_slug, g_pose)
		if g_tex == null or g_info.is_empty():
			continue
		var alpha: float = float(ghost["life"]) * 0.34
		_draw_sprite(
			g_tex, g_info, Vector2(ghost["pos"]) - position, float(ghost["rot"]),
			Color(accent.r, accent.g, accent.b, alpha)
		)

	if tex != null and not info.is_empty():
		var off := _pose_offset()
		var rot := _pose_rotation()
		_draw_sprite(tex, info, off, rot, Color(1, 1, 1, 1))
		if _hit_flash > 0.0:
			var flash_tex: Texture2D = Art.flash_texture(art_slug, pose)
			if flash_tex != null:
				var a: float = clampf(_hit_flash * 7.0, 0.0, 0.9)
				_draw_sprite(flash_tex, info, off, rot, Color(1, 1, 1, a))
		if _flying:
			var pulse: float = 0.12 + 0.05 * sin(_anim_t * 13.0)
			draw_set_transform(Vector2(0.0, -78.0), 0.0, Vector2(1.0, 1.0))
			draw_circle(Vector2.ZERO, 48.0, Color(accent.r, accent.g, accent.b, pulse))
			draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	else:
		# No artwork on disk: fall back to the code-drawn cel-shaded rig.
		NinjaLook.draw_fighter(self, _art_kind(), _art_keys(), pal, _anim_t, facing)

	# Guard shimmer while blocking.
	if state == State.BLOCK:
		var spark: float = 0.22 + 0.14 * sin(_anim_t * 9.0)
		draw_arc(
			Vector2(facing * 26.0, -92.0), 44.0, -1.15, 1.15, 18,
			Color(0.62, 0.9, 1.0, spark), 4.0, true
		)


func _draw_sprite(tex: Texture2D, info: Dictionary, offset: Vector2, rot: float, mod: Color) -> void:
	var s: float = float(info["s"])
	var w: float = float(info["w"]) * s
	var h: float = float(info["h"]) * s
	var ax: float = float(info["ax"]) * s
	var ay: float = float(info["ay"]) * s
	draw_set_transform(offset, rot, Vector2(facing, 1.0))
	draw_texture_rect(tex, Rect2(-ax, -ay, w, h), false, mod)
	draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)


func _art_pose() -> String:
	match state:
		State.RUN:
			return "run"
		State.AIR:
			return "air"
		State.ATTACK:
			return String(_move.get("pose", "attack")) if not _move.is_empty() else "attack"
		State.BLOCK:
			return "block"
		State.HURT:
			return "hurt"
		State.KO:
			return "ko"
	return "idle"


func _art_kind() -> String:
	match state:
		State.RUN:
			return "run"
		State.AIR:
			return "fly" if _flying else "air"
		State.ATTACK:
			return _art_pose()
		State.BLOCK:
			return "block"
		State.HURT:
			return "hurt"
		State.KO:
			return "ko"
	return "idle"


func _art_keys() -> Dictionary:
	var startup := float(_move.get("startup_f", 5)) / SkillDb.FPS if not _move.is_empty() else 0.08
	var frame_sec := float(_atk_frame) / SkillDb.FPS
	return {
		"step": _chain_index(),
		"atk_t": frame_sec,
		"startup": startup,
		"air": not grounded,
		"proj_t": frame_sec,
		"ko_t": _ko_t,
		"vy": velocity.y,
		"grounded": grounded,
		"flying": _flying,
	}


func _chain_index() -> int:
	"""Where the running move sits in the basic string, for the fallback rig."""
	if _move_slot != "basic" or def.is_empty():
		return 0
	return maxi(0, def.get("slots", {}).get("basic", []).find(String(_move.get("id", ""))))


func _pose_offset() -> Vector2:
	# Local-space offset of the character root; +X already means "forward".
	match state:
		State.IDLE:
			return Vector2(0.0, sin(_anim_t * 2.4) * 2.4)
		State.RUN:
			return Vector2(0.0, -absf(sin(_anim_t * 12.0)) * 3.0)
		State.AIR:
			return Vector2(facing * clampf(velocity.x * 0.012, -8.0, 8.0), 0.0)
		State.ATTACK:
			return Vector2(facing * _lunge(float(_move.get("lunge", 18.0))), 0.0)
		State.BLOCK:
			return Vector2(facing * -3.0, 3.0)
		State.HURT:
			return Vector2(facing * -7.0 + randf_range(-1.6, 1.6), randf_range(-1.6, 1.6))
		State.KO:
			var settle: float = clampf(_ko_t * 4.0, 0.0, 1.0)
			return Vector2(0.0, -(1.0 - settle) * 7.0)
	return Vector2.ZERO


func _lunge(amount: float) -> float:
	# Pull back during startup, snap forward through the active frames, ease home.
	var startup := float(_move.get("startup_f", 1))
	var active_end := startup + float(_move.get("active_f", 1))
	var t := float(_atk_frame)
	if t < startup:
		return -amount * 0.30 * (t / maxf(startup, 0.001))
	if t < active_end:
		return amount
	# Ease home over roughly the old 0.22 s.
	return amount * clampf(1.0 - (t - active_end) / 13.0, 0.0, 1.0)


func _pose_rotation() -> float:
	match state:
		State.AIR:
			return facing * clampf(velocity.y * 0.00013, -0.10, 0.14)
		State.HURT:
			return facing * -0.10
		State.ATTACK:
			if String(_move.get("kind", "")) == "launcher":
				return facing * 0.12
			return facing * 0.05
	return 0.0


func _update_ghosts(delta: float) -> void:
	_poof_cd = maxf(0.0, _poof_cd - delta)
	for g in _ghosts:
		var ghost: Dictionary = g
		ghost["life"] = float(ghost["life"]) - delta * 3.6
	_ghosts = _ghosts.filter(func(g): return float(g["life"]) > 0.0)
	if state == State.KO:
		return
	var fast: bool = absf(velocity.x) > 300.0 or _flying or (not grounded and velocity.length() > 480.0)
	if not fast:
		return
	_ghost_t -= delta
	if _ghost_t > 0.0:
		return
	_ghost_t = 0.05
	_ghosts.append({
		"pos": position,
		"pose": _art_pose(),
		"rot": _pose_rotation(),
		"life": 1.0,
	})
	# A soft smoke puff trailing the afterimages - the "shadow clone" flavour,
	# rate limited so a long flight does not turn into a hiss.
	if _poof_cd <= 0.0:
		_poof_cd = 0.85
		_sound("poof", -10.0)


# ---------------------------------------------------------------- audio

func _sound(event: String, volume_db := 0.0) -> void:
	if main != null and main.sfx != null:
		main.sfx.play_at(event, position + Vector2(0.0, -70.0), volume_db)


func _say(line: String) -> void:
	if main != null and main.sfx != null:
		main.sfx.say(line, position + Vector2(0.0, -92.0), voice_pitch)


func is_flying() -> bool:
	return _flying


func say_win() -> void:
	_say("win")



func _palette() -> Dictionary:
	if player_id == 1:
		return {
			"hair": Color("#2b2f45"),
			"hair_dark": Color("#1d2033"),
			"suit": Color("#2f6fbe"),
			"dark": Color("#1d3f77"),
			"vest": Color("#1f3f6e"),
			"vest_dark": Color("#152c4d"),
			"vest_line": Color("#0e2340"),
			"belt": Color("#16233b"),
			"pant": Color("#22304f"),
			"pant_dark": Color("#1a2540"),
			"shin": Color("#2f6fbe"),
			"shin_dark": Color("#24589b"),
			"sleeve": Color("#2f6fbe"),
			"sleeve_dark": Color("#24589b"),
			"guard": Color("#e07b34"),
			"guard_dark": Color("#b25e28"),
			"skin": Color("#f0c090"),
			"skin_dark": Color("#cf9d70"),
			"accent": Color("#ff9f2e"),
			"accent_dark": Color("#d97a18"),
			"band_cloth": Color("#22304d"),
			"sandal": Color("#2b3040"),
			"sandal_dark": Color("#1c202c"),
		}
	return {
		"hair": Color("#3a4058"),
		"hair_dark": Color("#262a3d"),
		"suit": Color("#3f9e5f"),
		"dark": Color("#245c38"),
		"vest": Color("#1f5a3a"),
		"vest_dark": Color("#16422b"),
		"vest_line": Color("#0e2f1e"),
		"belt": Color("#18241c"),
		"pant": Color("#223026"),
		"pant_dark": Color("#18241d"),
		"shin": Color("#3f9e5f"),
		"shin_dark": Color("#2f7c49"),
		"sleeve": Color("#3f9e5f"),
		"sleeve_dark": Color("#2f7c49"),
		"guard": Color("#c94f3f"),
		"guard_dark": Color("#9c3a2d"),
		"skin": Color("#d99a72"),
		"skin_dark": Color("#b87f5c"),
		"accent": Color("#ff5a5a"),
		"accent_dark": Color("#cc3f3f"),
		"band_cloth": Color("#2c3140"),
		"sandal": Color("#2b3040"),
		"sandal_dark": Color("#1c202c"),
	}
