class_name Orb
extends Node2D

const SkillDb = preload("res://scripts/skill_db.gd")

# Every number here is a fallback: the real values arrive from the shooting
# move's `projectile` block in the skill config, so a character can have a
# slow heavy orb and another a thin fast one without touching this file.
var dir := 1
var speed := 760.0
var dmg := 14.0
var radius := 13.0
var life := 2.4
var knockback := Vector2(430.0, -200.0)
var hitstun_f := 16
var blockstun_f := 14
var hitstop_f := 6
var hit_kind := "chakra_hit"
var hit_sfx := "chakra_hit"
var death_sfx := "poof"
var color := Color(0.55, 0.9, 1.0)
var shooter: Fighter = null
var main  # untyped: arena root
var _trail: Array = []
var _dead := false
var _impacted := false


func setup(caster: Fighter, arena, spec: Dictionary) -> void:
	shooter = caster
	main = arena
	speed = float(spec.get("speed", speed))
	dmg = float(spec.get("damage", dmg))
	radius = float(spec.get("radius", radius))
	life = SkillDb.seconds(float(spec.get("life_f", 144)))
	hitstun_f = int(spec.get("hitstun_f", hitstun_f))
	blockstun_f = int(spec.get("blockstun_f", blockstun_f))
	hitstop_f = int(spec.get("hitstop_f", hitstop_f))
	hit_kind = String(spec.get("hit_kind", hit_kind))
	hit_sfx = String(spec.get("hit_sfx", hit_sfx))
	death_sfx = String(spec.get("death_sfx", death_sfx))
	var rgb = spec.get("color")
	if rgb is Array and rgb.size() >= 3:
		color = Color(float(rgb[0]), float(rgb[1]), float(rgb[2]))
	dir = caster.facing
	position = caster.position + Vector2(caster.facing * 48.0, -80.0)


func _physics_process(delta: float) -> void:
	if main == null or _dead or main.frozen():
		return
	life -= delta
	position.x += dir * speed * delta
	_trail.push_front(position)
	if _trail.size() > 5:
		_trail.pop_back()
	if life <= 0.0 or position.x < shooter.arena_min_x - 30.0 or position.x > shooter.arena_max_x + 30.0:
		die()
		return
	if shooter != null and shooter.opponent != null:
		var orb_rect := Rect2(position.x - radius, position.y - radius, radius * 2.0, radius * 2.0)
		if orb_rect.intersects(shooter.opponent.hurt_rect()):
			_impacted = true
			shooter.opponent.take_hit(
				dmg,
				Vector2(dir * knockback.x, knockback.y),
				position, shooter, hit_kind, hitstun_f, blockstun_f, hitstop_f,
				[color.r, color.g, color.b],
			)
			die()


func die() -> void:
	if _dead:
		return
	_dead = true
	if main != null:
		main.spawn_fx(position, color, 34.0)
		if not _impacted:
			# Fizzling out at the edge of the arena: a small dissipating puff.
			main.sfx.play_at(death_sfx, position, -6.0)
		main.orbs.erase(self)
	queue_free()


func _draw() -> void:
	for i in _trail.size():
		var p: Vector2 = _trail[i] - position
		var a := 0.20 * (1.0 - float(i) / float(_trail.size()))
		draw_circle(p, radius * (1.0 - float(i) * 0.12), Color(color.r * 0.7, color.g * 0.85, color.b, a))
	draw_circle(Vector2.ZERO, radius, Color(color.r * 0.65, color.g * 0.8, color.b, 0.55))
	draw_circle(Vector2.ZERO, radius * 0.55, Color(0.9, 1.0, 1.0, 0.95))
