extends SceneTree

# Frame-time probe. Answers "why does it feel stuttery" with numbers instead of
# guessing, because a 2D game like this has three completely different failure
# modes that all look like "卡":
#
#   1. too heavy    - the frame takes longer than 16.7 ms, so frames are dropped
#   2. uneven       - frames are fast, but they arrive in a ragged rhythm
#   3. physics judder - rendering runs at 60 and physics runs at 60, but they are
#                       not locked together, so a moving body is drawn 1 frame
#                       then 2 frames in a row (this is the one that makes a
#                       game look choppy while the FPS counter says 60)
#
# Run it windowed (headless has no real renderer):
#
#   godot --path . -s res://tests/perf.gd -- <mode>
#
# Modes hide one subsystem each so the cost of the drawing can be attributed:
#   base | nobg | nohud | nosfx | noghost | novsync

const WARMUP := 90
const SAMPLES := 420

var _main = null
var _frames := 0
var _mode := "base"
var _mode_applied := false
var _deltas: Array[float] = []
var _steps_per_frame: Array[int] = []
var _last_physics := 0
var _last_ticks := 0
var _process_times: Array[float] = []
var _physics_times: Array[float] = []
var _samples: Array = []  # {frame, delta}


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	_mode = String(args[0]) if args.size() > 0 else "base"
	DisplayServer.window_set_size(Vector2i(1280, 720))
	if _mode == "novsync":
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
		Engine.max_fps = 0
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
	if _frames == 30 and not _mode_applied:
		_mode_applied = true
		_apply_mode()
		if _main.sfx != null:
			_main.sfx.clear_log()
			_main.sfx.log_events = true
		# Count from a fixed starting point; the first frames after a scene load
		# include shader compilation and are not what the player ever sees.
		_last_physics = Engine.get_physics_frames()
		_last_ticks = Time.get_ticks_usec()
		return
	if not _mode_applied or _frames <= WARMUP:
		# Keep the clock current during warmup, otherwise the first sampled
		# delta spans the whole warmup and pretends to be a 5-second hitch.
		_last_ticks = Time.get_ticks_usec()
		_last_physics = Engine.get_physics_frames()
		return
	if _mode == "noghost":
		for f in _main.fighters:
			f._ghosts.clear()

	var now := Time.get_ticks_usec()
	var delta_ms := float(now - _last_ticks) / 1000.0
	_deltas.append(delta_ms)
	_samples.append({
		"frame": _frames,
		"delta": delta_ms,
		"state": _snapshot(),
	})
	_last_ticks = now
	var steps := Engine.get_physics_frames() - _last_physics
	_last_physics = Engine.get_physics_frames()
	_steps_per_frame.append(steps)
	_process_times.append(Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0)
	_physics_times.append(Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0)

	if _deltas.size() < SAMPLES:
		return
	_report()
	quit(0)


func _apply_mode() -> void:
	match _mode:
		"nobg":
			for child in _main.get_children():
				if child is Bg:
					child.visible = false
		"nohud":
			var hud := _main.hud as CanvasLayer
			if hud != null:
				hud.visible = false
		"nosfx":
			AudioServer.set_bus_mute(0, true)
			_main.sfx.queue_free()
		"noghost":
			# The afterimage trail is rebuilt every frame by _update_ghosts, so
			# emptying it here each frame is the same as turning it off.
			pass


func _report() -> void:
	_deltas.sort()
	var total := 0.0
	for d in _deltas:
		total += d
	var avg := total / float(_deltas.size())
	var p50: float = _deltas[int(float(_deltas.size()) * 0.50)]
	var p95: float = _deltas[int(float(_deltas.size()) * 0.95)]
	var p99: float = _deltas[int(float(_deltas.size()) * 0.99)]
	var worst: float = _deltas[-1]
	var over_budget := 0
	var hitch := 0
	for d in _deltas:
		if d > 16.7 * 1.25:
			over_budget += 1
		if d > 33.4:
			hitch += 1

	var counts := {0: 0, 1: 0, 2: 0, 3: 0}
	for s in _steps_per_frame:
		counts[mini(s, 3)] = int(counts.get(mini(s, 3), 0)) + 1

	var proc_avg := 0.0
	for t in _process_times:
		proc_avg += t
	proc_avg /= float(_process_times.size())
	var phys_avg := 0.0
	for t in _physics_times:
		phys_avg += t
	phys_avg /= float(_physics_times.size())

	print("=== perf: mode=%s frames=%d ===" % [_mode, _deltas.size()])
	print("  平均帧时间 %.2f ms  →  %.1f FPS" % [avg, 1000.0 / maxf(avg, 0.001)])
	print("  p50 %.2f  p95 %.2f  p99 %.2f  最差 %.2f ms" % [p50, p95, p99, worst])
	print("  超预算帧（>20.9 ms）%d / %d（%.1f%%）  掉帧（>33.4 ms）%d"
		% [over_budget, _deltas.size(), 100.0 * float(over_budget) / float(_deltas.size()), hitch])
	print("  每渲染帧的物理步数：0步=%d  1步=%d  2步=%d  3步+=%d"
		% [counts[0], counts[1], counts[2], counts[3]])
	print("  引擎自报：process %.2f ms  physics %.2f ms  FPS %.1f"
		% [proc_avg, phys_avg, Performance.get_monitor(Performance.TIME_FPS)])
	var worst_list := _samples.duplicate()
	worst_list.sort_custom(func(a, b): return float(a["delta"]) > float(b["delta"]))
	var parts: Array[String] = []
	for i in mini(5, worst_list.size()):
		parts.append("第%d帧 %.1fms [%s]" % [int(worst_list[i]["frame"]), float(worst_list[i]["delta"]),
			String(worst_list[i]["state"])])
	print("  最差的五帧：" + "\n    ".join(parts))


# What the world looked like on the frame that took too long: which phase, how
# many effect nodes existed, and the last few sounds that had been triggered.
# A one-off multi-second stall is almost always a first-use cost, so the events
# that immediately precede it are the suspects.
func _snapshot() -> String:
	var fx := 0
	for child in _main.get_children():
		if child is FxPop:
			fx += 1
	var s := "%s t=%.1f fx=%d orb=%d hp=%.0f/%.0f" % [
		_main.phase, _main.fight_time, fx, _main.orbs.size(),
		_main.fighters[0].hp, _main.fighters[1].hp]
	if _main.sfx != null:
		var log: Array = _main.sfx.recorded()
		var tail: Array = log.slice(maxi(0, log.size() - 3))
		s += " sfx=[" + ", ".join(tail) + "]"
	return s
