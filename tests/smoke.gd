extends SceneTree

# Headless smoke test: load the arena, enable both fighters as CPU,
# then run until a match ends (KO or time-up). Exit 0 on success.

var _main = null
var _frames := 0
var _zero_hp_at := -1


func _initialize() -> void:
	change_scene_to_file("res://scenes/main.tscn")
	process_frame.connect(_tick)


func _tick() -> void:
	if _main == null:
		_main = root.get_node_or_null("Main")
		if _main != null:
			_main._start_match("sora", "kaze")
		return
	_frames += 1
	if _frames == 10:
		for f in _main.fighters:
			f.is_ai = true
	if _main.phase == "over":
		print("SMOKE OK: match ended after %d frames" % _frames)
		quit(0)
		return
	var zero_hp := false
	for f in _main.fighters:
		if f.hp <= 0.0:
			zero_hp = true
			break
	if zero_hp and _zero_hp_at < 0:
		_zero_hp_at = _frames
	if _zero_hp_at >= 0 and _main.phase != "over" and _frames - _zero_hp_at > 10:
		print("SMOKE FAIL: fighter reached 0 HP but phase stayed %s" % _main.phase)
		quit(1)
	if _frames > 99 * 60 + 300:
		print("SMOKE FAIL: match did not end")
		quit(1)
