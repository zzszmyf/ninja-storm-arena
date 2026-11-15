class_name DamagePop
extends Node2D

# Lightweight hit number. Drawing the glyph directly avoids constructing a
# Control, running theme layout, and allocating a Tween for every hit.
var value := 0
var age := 0.0
const LIFE := 0.5

func setup(pos: Vector2, amount: int) -> void:
	position = pos
	value = amount

func _process(delta: float) -> void:
	age += delta
	if age >= LIFE:
		queue_free()
		return
	position.y -= delta * 60.0
	queue_redraw()

func _draw() -> void:
	var alpha := 1.0 - clampf((age - 0.1) / 0.4, 0.0, 1.0)
	var font := ThemeDB.fallback_font
	var text := "-%d" % value
	draw_string_outline(font, Vector2.ZERO, text, HORIZONTAL_ALIGNMENT_LEFT, -1.0, 19, 4,
		Color(0.0, 0.0, 0.0, alpha * 0.9))
	draw_string(font, Vector2.ZERO, text, HORIZONTAL_ALIGNMENT_LEFT, -1.0, 19,
		Color(1.0, 0.9, 0.6, alpha))
