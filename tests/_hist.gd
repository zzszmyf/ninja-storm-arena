extends SceneTree
var _main = null
var _frames := 0
func _initialize() -> void:
	change_scene_to_file("res://scenes/main.tscn")
	process_frame.connect(_tick)
func _tick() -> void:
	if _main == null:
		_main = root.get_node_or_null("Main")
		return
	_frames += 1
	if _frames == 3:
		_main.sfx.log_events = true
		_main.sfx.clear_log()
		for f in _main.fighters:
			f.is_ai = true
		return
	if _frames == 700:
		var hist := {}
		for e in _main.sfx.recorded():
			hist[e] = int(hist.get(e, 0)) + 1
		var keys := hist.keys()
		keys.sort()
		for k in keys:
			print("  ", k, " x", hist[k])
		print("total ", _main.sfx.recorded().size())
		quit(0)
