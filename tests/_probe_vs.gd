extends SceneTree

var _main = null
var _f := 0
var _t0 := 0
var _marks := [30, 60, 66, 70, 80, 85, 90, 100, 105, 110, 120, 200, 400]


func _initialize() -> void:
	_t0 = Time.get_ticks_msec()
	change_scene_to_file("res://scenes/main.tscn")
	process_frame.connect(_tick)


func _tick() -> void:
	if _main == null:
		_main = root.get_node_or_null("Main")
		return
	_f += 1
	if _f in _marks:
		_dump(_f)
	if _f == 200:
		_dump_hud()
	if _f > 420:
		quit(0)


func _dump(f: int) -> void:
	var l = _main._vs_left
	var r = _main._vs_right
	var pl = l.get_meta("panel")
	var pr = r.get_meta("panel")
	print("frame %d  t=%.2fs  phase_t=%.2f  phase=%s  L(x=%.0f a=%.2f vis=%s) R(x=%.0f a=%.2f vis=%s)  panels(L a=%.2f pos=%.0f vis=%s, R a=%.2f pos=%.0f vis=%s)"
		% [f, (Time.get_ticks_msec() - _t0) / 1000.0, _main.phase_t, _main.phase,
		   l.position.x, l.modulate.a, l.visible, r.position.x, r.modulate.a, r.visible,
		   pl.color.a, pl.position.x, pl.visible, pr.color.a, pr.position.x, pr.visible])


func _dump_hud() -> void:
	for player in [1, 2]:
		var tr = _main._portrait.get(player)
		if tr == null:
			print("player %d: no portrait node" % player)
			continue
		var tex: Texture2D = tr.texture
		print("player %d portrait: node size=%s  min=%s  tex=%s  expand=%d  pos=%s  clip=%s"
			% [player, tr.size, tr.get_minimum_size(),
			   "%dx%d" % [tex.get_width(), tex.get_height()] if tex else "none",
			   tr.expand_mode, tr.position, tr.clip_contents])
