class_name FxPop
extends Node2D

var t := 0.0
var life := 0.28
var color := Color(1, 1, 1)
var max_radius := 26.0


func setup(pos: Vector2, c: Color, radius: float) -> void:
	position = pos
	color = c
	max_radius = radius


func _process(delta: float) -> void:
	t += delta
	if t >= life:
		queue_free()
		return
	queue_redraw()


func _draw() -> void:
	var p := clampf(t / life, 0.0, 1.0)
	var r := max_radius * (0.3 + 0.7 * p)
	var alpha := (1.0 - p)
	# hot core first
	draw_circle(Vector2.ZERO, r * 0.35, Color(color.r, color.g, color.b, alpha * 0.9))
	# expanding ring
	draw_arc(Vector2.ZERO, r, 0.0, TAU, 24, Color(color.r, color.g, color.b, alpha * 0.8), 3.0, true)
	if p < 0.5:
		draw_circle(Vector2.ZERO, r * 0.55, Color(1, 1, 1, alpha * 0.35))
