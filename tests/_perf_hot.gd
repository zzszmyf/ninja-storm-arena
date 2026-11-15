extends SceneTree

# Companion probe to perf.gd. perf.gd measures the game the way a player sees
# it (vsync on, 120 Hz panel), which tells you *that* it judders but not *what*
# it costs, because vsync hides every millisecond under the refresh budget.
#
# The uncapped modes hide one subsystem each, so the achieved frame time
# differences read directly as "how much does this cost". The remaining modes
# keep the frame rate the player actually gets and measure cadence instead:
# how many rendered frames sit between two simulation steps, and how often a
# frame draws a fighter at the exact coordinate it already had.
#
#   godot --path . -s res://tests/_perf_hot.gd -- <mode>
#     default                                   shipped config, untouched
#     raw | nofighters | nohud | nobg | nosfx   cost attribution, uncapped
#     vsync                                     exactly what the player sees
#     cap60                                     with the render rate capped

const WARMUP := 120
const SAMPLES := 600

var _main = null
var _frames := 0
var _mode := "raw"
var _armed := false
var _deltas: Array[float] = []
var _steps: Array[int] = []
var _frozen_frames := 0
var _last_physics := 0
var _last_usec := 0
var _prev_x := {}
var _moving_frames := 0
var _repeated_pos := 0
var _spikes: Array[String] = []
var _gaps: Array[int] = []  # render frames between two physics steps
var _since_step := 0


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	_mode = String(args[0]) if args.size() > 0 else "raw"
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
	if _frames == 40 and not _armed:
		_armed = true
		_apply_rate_mode()
		_apply_mode()
		_last_physics = Engine.get_physics_frames()
		_last_usec = Time.get_ticks_usec()
		return
	if not _armed or _frames <= WARMUP:
		_last_usec = Time.get_ticks_usec()
		_last_physics = Engine.get_physics_frames()
		_seed_positions()
		return

	var now := Time.get_ticks_usec()
	var delta_ms := float(now - _last_usec) / 1000.0
	_last_usec = now
	var step := Engine.get_physics_frames() - _last_physics
	_last_physics = Engine.get_physics_frames()
	_deltas.append(delta_ms)
	_steps.append(step)
	# Cadence, not throughput: how many render frames sit between two
	# simulation steps. A rock-steady 60 Hz sim on a 120 Hz panel gives a
	# constant 2. Values of 1 and 3 alternating instead mean the renderer and
	# the simulation are drifting in and out of phase, which reads as judder
	# even though the average is correct.
	if step > 0:
		_gaps.append(_since_step + 1)
		_since_step = 0
	else:
		_since_step += 1
	if delta_ms > 33.4:
		_spikes.append("第%d帧 %.0fms" % [_frames, delta_ms])

	# "Did the simulation actually advance this render frame?" A fighter that
	# is mid-run and whose x is byte-identical to the previous render frame was
	# drawn twice from one simulation state.
	for f in _main.fighters:
		var id: int = f.player_id
		var x: float = f.position.x
		var prev = _prev_x.get(id, null)
		if prev != null and absf(f.velocity.x) > 1.0:
			_moving_frames += 1
			if is_equal_approx(prev, x):
				_repeated_pos += 1
		_prev_x[id] = x
	if step == 0:
		_frozen_frames += 1

	if _deltas.size() < SAMPLES:
		return
	_report()
	quit(0)


func _seed_positions() -> void:
	for f in _main.fighters:
		_prev_x[f.player_id] = f.position.x


# Vsync has to be pushed down after the window exists, otherwise the driver's
# 120 Hz present queue wins and every sample lands on exactly 8.33 ms no matter
# what the game actually costs. Done once, from the frame loop, so the setters
# themselves cannot show up as a hitch in the samples.
func _apply_rate_mode() -> void:
	if _mode == "default":
		# Measures the project exactly as it ships, including its max_fps. This
		# is the mode to re-run after touching anything about frame pacing.
		return
	if _mode == "cap60":
		# Candidate fix: lock the renderer to the simulation rate. A 60 Hz
		# fighting game presenting at 60 Hz gets one physics step per frame and
		# an even cadence on any panel.
		Engine.max_fps = 60
		return
	DisplayServer.window_set_vsync_mode(
		DisplayServer.VSYNC_ENABLED if _mode == "vsync" else DisplayServer.VSYNC_DISABLED)
	Engine.max_fps = 0


func _apply_mode() -> void:
	match _mode:
		"nofighters":
			for f in _main.fighters:
				f.visible = false
		"nohud":
			(_main.hud as CanvasLayer).visible = false
		"nobg":
			for child in _main.get_children():
				if child is Bg:
					child.visible = false
		"nosfx":
			AudioServer.set_bus_mute(0, true)


func _report() -> void:
	var sorted := _deltas.duplicate()
	sorted.sort()
	var total := 0.0
	for d in _deltas:
		total += d
	var avg := total / float(_deltas.size())
	var p50: float = sorted[int(float(sorted.size()) * 0.50)]
	var p95: float = sorted[int(float(sorted.size()) * 0.95)]
	var p99: float = sorted[int(float(sorted.size()) * 0.99)]
	var worst: float = sorted[-1]
	var counts := [0, 0, 0, 0]
	for s in _steps:
		counts[mini(s, 3)] += 1

	print("=== hot: mode=%s frames=%d ===" % [_mode, _deltas.size()])
	print("  帧时间 avg %.2f ms (%.0f FPS)  p50 %.2f  p95 %.2f  p99 %.2f  最差 %.2f"
		% [avg, 1000.0 / maxf(avg, 0.001), p50, p95, p99, worst])
	print("  每渲染帧物理步数：0步=%d(%.0f%%)  1步=%d  2步=%d  3步+=%d"
		% [counts[0], 100.0 * counts[0] / float(_steps.size()), counts[1], counts[2], counts[3]])
	if _moving_frames > 0:
		print("  移动中的渲染帧 %d，其中 %d 帧(%.0f%%)和前一个渲染帧坐标完全相同"
			% [_moving_frames, _repeated_pos, 100.0 * _repeated_pos / float(_moving_frames)])
	print("  引擎自报：process %.2f ms  physics %.2f ms"
		% [Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0,
			Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0])
	print("  >33ms 的卡顿点：%d 个%s" % [_spikes.size(),
		("  " + ", ".join(_spikes.slice(0, 8))) if _spikes.size() > 0 else ""])
	var gap_hist := {}
	for g in _gaps:
		gap_hist[g] = int(gap_hist.get(g, 0)) + 1
	var gap_keys := gap_hist.keys()
	gap_keys.sort()
	var parts: Array[String] = []
	for k in gap_keys:
		parts.append("隔%s帧 %d 次(%.0f%%)" % [k, gap_hist[k],
			100.0 * float(gap_hist[k]) / float(maxi(_gaps.size(), 1))])
	print("  两次物理步之间的渲染帧数分布：" + ("  ".join(parts) if parts.size() > 0 else "无数据"))
