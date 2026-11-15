extends SceneTree

# Dev tool: renders the intro, a mid-fight moment and the KO finish to PNGs
# under /private/tmp so the artwork can be eyeballed.

var _main = null
var _frames := 0
var _over_at := -1
var _fight_start_at := -1


func _initialize() -> void:
	DisplayServer.window_set_size(Vector2i(1280, 720))
	change_scene_to_file("res://scenes/main.tscn")
	process_frame.connect(_tick)


func _tick() -> void:
	if _main == null:
		_main = root.get_node_or_null("Main")
		return
	_frames += 1
	if _frames == 5:
		for f in _main.fighters:
			f.is_ai = true
	if _frames == 45:
		_save("intro")
	# The frame the match becomes playable is the one that matters: nothing may
	# be left floating over the arena once the fighters can move.
	if _main.phase == "fight" and _fight_start_at < 0:
		_fight_start_at = _frames
		_save("fight_start")
	if _frames == 420:
		_save("fight_a")
	if _frames == 900:
		_save("fight_b")
	if _main.phase == "over" and _over_at < 0:
		_over_at = _frames
	if _over_at > 0 and _frames == _over_at + 40:
		_save("ko")
		quit(0)
		return
	if _frames > 99 * 60 + 400:
		quit(1)


func _save(name: String) -> void:
	var img: Image = root.get_texture().get_image()
	img.save_png("/private/tmp/ninja_%s.png" % name)
	print("saved ", name, " (", img.get_width(), "x", img.get_height(), ")")
