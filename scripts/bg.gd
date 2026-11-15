class_name Bg
extends Node2D

# Arena backdrop. Uses the generated anime stage painting when it exists and
# falls back to a code-painted dusk sky otherwise, then layers drifting leaves
# and a foreground vignette on top so the scene never looks static.

var _stage: Texture2D = null
var _t := 0.0
var _leaves: Array = []
# Fixed seed so the backdrop is the same picture every run (screenshots and
# visual comparisons depend on that). Kept as a member, and never the global
# generator, so respawning a leaf cannot advance the stream the fight logic
# draws from - that would make the CPU's decisions depend on the frame rate.
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	_stage = Art.stage_texture()
	_rng.seed = 20260917
	for i in 30:
		_leaves.append({
			"pos": Vector2(_rng.randf_range(-60.0, 1340.0), _rng.randf_range(-40.0, 700.0)),
			"speed": _rng.randf_range(26.0, 74.0),
			"drift": _rng.randf_range(14.0, 40.0),
			"size": _rng.randf_range(3.0, 7.5),
			"phase": _rng.randf_range(0.0, TAU),
			"warm": _rng.randf(),
		})
	queue_redraw()


func _process(delta: float) -> void:
	_t += delta
	for l in _leaves:
		var leaf: Dictionary = l
		var pos: Vector2 = leaf["pos"]
		pos.x -= float(leaf["speed"]) * delta
		pos.y += sin(_t * 1.6 + float(leaf["phase"])) * float(leaf["drift"]) * delta
		if pos.x < -80.0:
			pos.x = 1340.0
			pos.y = _rng.randf_range(-40.0, 700.0)
		if pos.y > 740.0:
			pos.y = -30.0
		leaf["pos"] = pos
	queue_redraw()


func _draw() -> void:
	if _stage != null:
		draw_texture_rect(_stage, Rect2(0.0, 0.0, 1280.0, 720.0), false)
	else:
		_draw_fallback_sky()

	_draw_leaves()

	# Foreground vignette: seats the fighters on the ground and focuses the middle.
	draw_rect(Rect2(0.0, 0.0, 1280.0, 74.0), Color(0.05, 0.03, 0.09, 0.28))
	draw_rect(Rect2(0.0, 660.0, 1280.0, 60.0), Color(0.04, 0.02, 0.07, 0.34))


func _draw_leaves() -> void:
	for l in _leaves:
		var leaf: Dictionary = l
		var pos: Vector2 = leaf["pos"]
		var s: float = float(leaf["size"])
		var warm: float = float(leaf["warm"])
		var col := Color(0.95, 0.72 + warm * 0.18, 0.55 + warm * 0.2, 0.5)
		var spin: float = _t * 2.4 + float(leaf["phase"])
		var side := Vector2(cos(spin), sin(spin)) * s
		var perp := Vector2(-side.y, side.x)
		draw_colored_polygon(
			PackedVector2Array([pos - side, pos + perp, pos + side, pos - perp]),
			col
		)


func _draw_fallback_sky() -> void:
	var top_c := Color("#26244f")
	var mid_c := Color("#7a4a7a")
	var hor_c := Color("#e88a5a")
	var rows := 18
	for i in rows:
		var t: float = float(i) / float(rows - 1)
		var c := top_c.lerp(mid_c, t)
		c = c.lerp(hor_c, clampf(t * 1.7 - 0.65, 0.0, 1.0))
		draw_rect(Rect2(0.0, float(i) * 40.0, 1280.0, 40.5), c)
	for i in 22:
		var x: float = fmod(float(i) * 137.0 + 31.0, 1280.0)
		var y: float = fmod(float(i) * 89.0 + 17.0, 170.0)
		draw_circle(Vector2(x, y), 1.2, Color(1, 1, 1, 0.35))
	draw_circle(Vector2(985, 250), 76.0, Color(1, 0.82, 0.5, 0.45))
	draw_circle(Vector2(985, 250), 52.0, Color(1, 0.9, 0.62, 0.9))
	draw_colored_polygon(
		PackedVector2Array([
			Vector2(0, 560), Vector2(130, 430), Vector2(270, 545), Vector2(420, 470),
			Vector2(580, 560), Vector2(1280, 505), Vector2(1280, 620), Vector2(0, 620),
		]),
		Color("#4a2f5a")
	)
	draw_colored_polygon(
		PackedVector2Array([
			Vector2(0, 585), Vector2(95, 505), Vector2(220, 575), Vector2(360, 520),
			Vector2(520, 590), Vector2(720, 530), Vector2(900, 590), Vector2(1080, 540),
			Vector2(1280, 590), Vector2(1280, 620), Vector2(0, 620),
		]),
		Color("#2f2347")
	)
	draw_rect(Rect2(0.0, 600.0, 1280.0, 120.0), Color("#4c3428"))
	draw_rect(Rect2(0.0, 600.0, 1280.0, 22.0), Color("#5f4632"))
	draw_rect(Rect2(0.0, 596.0, 1280.0, 8.0), Color("#68a44d"))
