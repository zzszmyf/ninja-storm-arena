extends Node2D

const SkillDb = preload("res://scripts/skill_db.gd")
const DamagePop = preload("res://scripts/damage_pop.gd")
const Sfx = preload("res://scripts/sfx.gd")
const Fighter = preload("res://scripts/fighter.gd")
const Orb = preload("res://scripts/orb.gd")
const FxPop = preload("res://scripts/fx.gd")
const Art = preload("res://scripts/art.gd")
const InputSetup = preload("res://scripts/input_setup.gd")

const GROUND_Y := 600.0
const ARENA_MIN_X := 70.0
const ARENA_MAX_X := 1210.0
const ROUND_TIME := 99.0
# The READY stamp shows for FIGHT_AT seconds; the versus cards start leaving
# INTRO_OUT_AT and take INTRO_OUT_TIME, so the arena is already clear on the
# exact frame the match becomes playable.
const FIGHT_AT := 1.1
const INTRO_OUT_AT := 0.78
const INTRO_OUT_TIME := 0.32

var cam: Camera2D
var hud: CanvasLayer
var sfx: Sfx
var fighters: Array[Fighter] = []
var orbs: Array = []

var phase := "ready"  # ready -> fight -> over
var phase_t := 0.0
var fight_time := ROUND_TIME
var round_started := false
var round_over := false
var paused := false

var freeze_until := 0
var trauma := 0.0
# Camera shake is cosmetic, so it gets its own generator instead of drawing from
# the global one. The global stream is what the CPU's move picking and the
# audio jitter use, and it is drawn from at simulation rates - if the shake
# pulled from it once per *rendered* frame, then how the CPU fights would
# change with the frame rate, and a match would stop being reproducible at all.
var _shake_rng := RandomNumberGenerator.new()

# HUD references
var _timer_label: Label
var _phase_label: Label
var _hint_label: Label
var _p1_name_label: Label
var _p2_name_label: Label
var _bars := {}  # player_id -> {bg, fill, x, w, kind}
var _phase_tween: Tween
var _portrait := {}  # player_id -> TextureRect
var _flash_rect: ColorRect
var _ko_label: Label
var _pause_overlay: ColorRect
var _pause_label: Label
var _pause_hint: Label
var _combo_label: Label
var _combo_label_tween: Tween
var _vs_left: TextureRect
var _vs_right: TextureRect
var _vs_tween: Tween
var _intro_out_done := false
var _combo_owner = null
var _combo_count := 0
var _combo_timer := 0.0
var _menu_layer: CanvasLayer
var _menu_main_panel: Control
var _menu_select_panel: Control
var _menu_result_panel: Control
var _menu_main_cursor := 0
var _menu_select_cursor := 0
var _p1_slug := "sora"
var _p2_slug := "kaze"
var _cpu_enabled := true
var _menu_p1_name: Label
var _menu_p2_name: Label
var _menu_cpu_name: Label
var _menu_select_hint: Label
var _match_generation := 0
var _menu_options: Array[Label] = []
var _impact_tween: Tween
var _zoom_tween: Tween
var _ko_tween: Tween


func _ready() -> void:
	InputSetup.new().setup()
	randomize()
	_shake_rng.randomize()
	sfx = Sfx.new()
	add_child(sfx)

	cam = Camera2D.new()
	cam.position = Vector2(640, 360)
	cam.limit_left = 0
	cam.limit_top = 0
	cam.limit_right = 1280
	cam.limit_bottom = 720
	cam.enabled = true
	add_child(cam)
	cam.make_current()

	var bg := preload("res://scripts/bg.gd").new()
	add_child(bg)

	phase = "menu"
	_build_menu()


func _process(delta: float) -> void:
	if phase == "menu":
		_process_menu_input()
		return
	if phase == "over":
		if Input.is_action_just_pressed("rematch") or Input.is_action_just_pressed("ui_accept"):
			_start_match(_p1_slug, _p2_slug)
			return
		if Input.is_action_just_pressed("ui_cancel"):
			_show_main_menu()
			return
	if Input.is_action_just_pressed("pause") and phase != "over":
		_toggle_pause()
	if paused:
		if Input.is_action_just_pressed("rematch"):
			_start_match(_p1_slug, _p2_slug)
			return
		_update_hud()
		return
	match phase:
		"ready":
			phase_t += delta
			if phase_t >= INTRO_OUT_AT:
				_play_intro_out()
			if phase_t >= FIGHT_AT:
				phase = "fight"
				round_started = true
				_show_phase_text("FIGHT!")
				sfx.play("round_start")
				sfx.duck(5.0, 0.9)
		"fight":
			if not round_over:
				fight_time = maxf(0.0, fight_time - delta)
				_timer_label.text = "%02d" % ceili(fight_time)
				if _check_ko():
					pass
				elif fight_time <= 0.0:
					_time_up()
		"over":
			pass

	_update_hud()
	_update_shake(delta)
	_update_aura()
	if _combo_timer > 0.0:
		_combo_timer = maxf(0.0, _combo_timer - delta)
		if _combo_timer == 0.0:
			_combo_count = 0
			_combo_owner = null

	if Input.is_action_just_pressed("rematch"):
		_start_match(_p1_slug, _p2_slug)
		return
	if Input.is_action_just_pressed("ui_cancel"):
		_show_main_menu()
	if Input.is_action_just_pressed("toggle_cpu") and not round_over:
		fighters[1].is_ai = not fighters[1].is_ai
		_p2_name_label.text = "KAZE" + ("  [CPU]" if fighters[1].is_ai else "  [P2]")
	if Input.is_action_just_pressed("mute"):
		var muted := sfx.toggle_mute()
		_show_phase_text("SOUND OFF" if muted else "SOUND ON")
	if Input.is_action_just_pressed("quit"):
		get_tree().quit()


# --------------------------------------------------------------- front end

func _build_menu() -> void:
	_menu_layer = CanvasLayer.new()
	_menu_layer.layer = 20
	add_child(_menu_layer)
	var shade := ColorRect.new()
	shade.color = Color(0.025, 0.018, 0.06, 0.72)
	shade.size = Vector2(1280, 720)
	shade.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_menu_layer.add_child(shade)

	_menu_main_panel = Control.new()
	_menu_main_panel.size = Vector2(1280, 720)
	_menu_layer.add_child(_menu_main_panel)
	_menu_label(_menu_main_panel, "忍者风暴竞技场", Vector2(160, 112), Vector2(960, 100), 58, Color(1.0, 0.83, 0.45), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_label(_menu_main_panel, "NINJA STORM ARENA", Vector2(160, 205), Vector2(960, 34), 20, Color(0.82, 0.88, 1.0), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_label(_menu_main_panel, "夕阳下的忍者对决，现在开始。", Vector2(160, 260), Vector2(960, 40), 22, Color(0.9, 0.91, 1.0), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_options = [
		_menu_label(_menu_main_panel, "开始游戏", Vector2(470, 382), Vector2(340, 54), 32, Color.WHITE, HORIZONTAL_ALIGNMENT_CENTER),
		_menu_label(_menu_main_panel, "操作说明", Vector2(470, 448), Vector2(340, 44), 24, Color(0.8, 0.84, 0.95), HORIZONTAL_ALIGNMENT_CENTER),
		_menu_label(_menu_main_panel, "退出游戏", Vector2(470, 504), Vector2(340, 44), 24, Color(0.8, 0.84, 0.95), HORIZONTAL_ALIGNMENT_CENTER),
	]
	_menu_label(_menu_main_panel, "↑ ↓ 选择     Enter 确认", Vector2(350, 620), Vector2(580, 36), 18, Color(0.72, 0.78, 0.9), HORIZONTAL_ALIGNMENT_CENTER)

	_menu_select_panel = Control.new()
	_menu_select_panel.size = Vector2(1280, 720)
	_menu_select_panel.visible = false
	_menu_layer.add_child(_menu_select_panel)
	_menu_label(_menu_select_panel, "选择你的忍者", Vector2(300, 52), Vector2(680, 70), 44, Color(1.0, 0.83, 0.45), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_label(_menu_select_panel, "左右切换角色，Enter 开始对战", Vector2(300, 118), Vector2(680, 34), 18, Color(0.82, 0.87, 0.98), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_select_card(_menu_select_panel, "P1", Rect2(160, 190, 390, 310), Color(0.13, 0.24, 0.48, 0.88))
	_menu_select_card(_menu_select_panel, "P2", Rect2(730, 190, 390, 310), Color(0.12, 0.34, 0.22, 0.88))
	_menu_p1_name = _menu_label(_menu_select_panel, "", Vector2(190, 510), Vector2(330, 52), 32, Color(0.65, 0.82, 1.0), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_p2_name = _menu_label(_menu_select_panel, "", Vector2(760, 510), Vector2(330, 52), 32, Color(0.68, 1.0, 0.72), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_cpu_name = _menu_label(_menu_select_panel, "", Vector2(390, 574), Vector2(500, 42), 22, Color(1, 1, 1), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_label(_menu_select_panel, "开始对战", Vector2(490, 624), Vector2(300, 48), 30, Color(1.0, 0.83, 0.45), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_label(_menu_select_panel, "Esc 返回主菜单", Vector2(490, 678), Vector2(300, 28), 16, Color(0.72, 0.78, 0.9), HORIZONTAL_ALIGNMENT_CENTER)
	_update_character_select()

	_menu_result_panel = Control.new()
	_menu_result_panel.size = Vector2(1280, 720)
	_menu_result_panel.visible = false
	_menu_layer.add_child(_menu_result_panel)
	var result_shade := ColorRect.new()
	result_shade.color = Color(0.025, 0.018, 0.06, 0.7)
	result_shade.size = Vector2(1280, 720)
	result_shade.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_menu_result_panel.add_child(result_shade)
	_menu_label(_menu_result_panel, "本局结束", Vector2(320, 390), Vector2(640, 56), 40, Color(1, 0.82, 0.42), HORIZONTAL_ALIGNMENT_CENTER)
	_menu_label(_menu_result_panel, "Enter / R  再来一局       Esc  回主菜单", Vector2(260, 454), Vector2(760, 42), 22, Color.WHITE, HORIZONTAL_ALIGNMENT_CENTER)
	_menu_main_cursor = 0
	_update_main_menu_cursor()


func _menu_label(parent: Control, text: String, at: Vector2, box: Vector2, font_size: int,
		color: Color, align: int) -> Label:
	var label := Label.new()
	label.text = text
	label.position = at
	label.size = box
	label.horizontal_alignment = align
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	label.add_theme_color_override("font_outline_color", Color(0.01, 0.01, 0.025, 0.9))
	label.add_theme_constant_override("outline_size", 5)
	parent.add_child(label)
	return label


func _menu_select_card(parent: Control, tag: String, rect: Rect2, color: Color) -> void:
	var plate := ColorRect.new()
	plate.position = rect.position
	plate.size = rect.size
	plate.color = color
	plate.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(plate)
	var border := ColorRect.new()
	border.position = rect.position - Vector2(3, 3)
	border.size = rect.size + Vector2(6, 6)
	border.color = Color(0.9, 0.75, 0.38, 0.8)
	border.z_index = -1
	border.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(border)
	_menu_label(parent, tag, rect.position + Vector2(12, 8), Vector2(50, 34), 20, Color(1, 0.86, 0.53), HORIZONTAL_ALIGNMENT_LEFT)
	var portrait := TextureRect.new()
	portrait.name = tag + "Portrait"
	portrait.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	portrait.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	portrait.position = rect.position + Vector2(92, 22)
	portrait.size = Vector2(206, 250)
	parent.add_child(portrait)


func _process_menu_input() -> void:
	if Input.is_action_just_pressed("ui_cancel"):
		if _menu_select_panel.visible:
			_show_main_menu()
		else:
			get_tree().quit()
		return
	if _menu_main_panel.visible:
		if Input.is_action_just_pressed("ui_down"):
			_menu_main_cursor = (_menu_main_cursor + 1) % 3
			_update_main_menu_cursor()
		elif Input.is_action_just_pressed("ui_up"):
			_menu_main_cursor = (_menu_main_cursor + 2) % 3
			_update_main_menu_cursor()
		elif Input.is_action_just_pressed("ui_accept"):
			match _menu_main_cursor:
				0:
					_menu_main_panel.visible = false
					_menu_select_panel.visible = true
					_menu_select_cursor = 0
					_update_character_select()
				1:
					for node in _menu_main_panel.get_children():
						if node is Label and node.text.begins_with("↑ ↓"):
							node.text = "WASD 移动   J 普攻   K 忍术   U 奥义   Q 替身   P 暂停"
				2:
					get_tree().quit()
		return
	if not _menu_select_panel.visible:
		return
	if Input.is_action_just_pressed("ui_up"):
		_menu_select_cursor = posmod(_menu_select_cursor - 1, 4)
		_update_character_select()
	elif Input.is_action_just_pressed("ui_down"):
		_menu_select_cursor = posmod(_menu_select_cursor + 1, 4)
		_update_character_select()
	elif Input.is_action_just_pressed("ui_left") or Input.is_action_just_pressed("ui_right"):
		if _menu_select_cursor == 0:
			_p1_slug = _other_character(_p1_slug)
		elif _menu_select_cursor == 1:
			_p2_slug = _other_character(_p2_slug)
		elif _menu_select_cursor == 2:
			_cpu_enabled = not _cpu_enabled
		_update_character_select()
	elif Input.is_action_just_pressed("ui_accept"):
		if _menu_select_cursor == 2:
			_cpu_enabled = not _cpu_enabled
			_update_character_select()
		elif _menu_select_cursor == 3:
			_start_match(_p1_slug, _p2_slug)


func _other_character(slug: String) -> String:
	return "kaze" if slug == "sora" else "sora"


func _update_main_menu_cursor() -> void:
	var names := ["开始游戏", "操作说明", "退出游戏"]
	for i in _menu_options.size():
		_menu_options[i].text = ("▶  " if i == _menu_main_cursor else "") + names[i]
		_menu_options[i].add_theme_color_override("font_color", Color(1.0, 0.83, 0.45) if i == _menu_main_cursor else Color(0.8, 0.84, 0.95))


func _update_character_select() -> void:
	if _menu_p1_name == null:
		return
	_menu_p1_name.text = ("▶  " if _menu_select_cursor == 0 else "") + Art.display_name(_p1_slug)
	_menu_p2_name.text = ("▶  " if _menu_select_cursor == 1 else "") + Art.display_name(_p2_slug)
	_menu_p1_name.add_theme_color_override("font_color", Color(1.0, 0.83, 0.45) if _menu_select_cursor == 0 else Color(0.65, 0.82, 1.0))
	_menu_p2_name.add_theme_color_override("font_color", Color(1.0, 0.83, 0.45) if _menu_select_cursor == 1 else Color(0.68, 1.0, 0.72))
	_menu_cpu_name.text = ("▶  " if _menu_select_cursor == 2 else "") + "对手模式：" + ("CPU" if _cpu_enabled else "双人")
	_menu_cpu_name.add_theme_color_override("font_color", Color(1.0, 0.83, 0.45) if _menu_select_cursor == 2 else Color.WHITE)
	var portrait1 := _menu_select_panel.get_node("P1Portrait") as TextureRect
	var portrait2 := _menu_select_panel.get_node("P2Portrait") as TextureRect
	portrait1.texture = Art.portrait_texture(_p1_slug)
	portrait2.texture = Art.portrait_texture(_p2_slug)


func _start_match(p1: String, p2: String) -> void:
	_match_generation += 1
	_cancel_visual_tweens()
	_p1_slug = p1
	_p2_slug = p2
	for f in fighters:
		if is_instance_valid(f):
			f.queue_free()
	fighters.clear()
	for orb in orbs:
		if is_instance_valid(orb):
			orb.queue_free()
	orbs.clear()
	if hud != null and is_instance_valid(hud):
		hud.queue_free()
	phase = "ready"
	phase_t = 0.0
	fight_time = ROUND_TIME
	round_started = false
	round_over = false
	paused = false
	freeze_until = 0
	trauma = 0.0
	_intro_out_done = false
	_combo_owner = null
	_combo_count = 0
	_combo_timer = 0.0
	cam.position = Vector2(640, 360)
	cam.zoom = Vector2.ONE
	cam.offset = Vector2.ZERO
	_spawn_fighter(1, Vector2(420, GROUND_Y), _p1_slug, false)
	_spawn_fighter(2, Vector2(860, GROUND_Y), _p2_slug, _cpu_enabled)
	fighters[0].opponent = fighters[1]
	fighters[1].opponent = fighters[0]
	_build_hud()
	_menu_main_panel.visible = false
	_menu_select_panel.visible = false
	_menu_result_panel.visible = false
	_show_phase_text("READY")
	_play_intro()
	sfx.music("battle_loop")


func _show_main_menu() -> void:
	_match_generation += 1
	_cancel_visual_tweens()
	for f in fighters:
		if is_instance_valid(f):
			f.queue_free()
	fighters.clear()
	for orb in orbs:
		if is_instance_valid(orb):
			orb.queue_free()
	orbs.clear()
	if hud != null and is_instance_valid(hud):
		hud.queue_free()
	phase = "menu"
	paused = false
	round_started = false
	round_over = false
	cam.position = Vector2(640, 360)
	cam.zoom = Vector2.ONE
	_menu_result_panel.visible = false
	_menu_select_panel.visible = false
	_menu_main_panel.visible = true
	_update_main_menu_cursor()


func _cancel_visual_tweens() -> void:
	for tw in [_phase_tween, _vs_tween, _combo_label_tween, _impact_tween, _zoom_tween, _ko_tween]:
		if tw != null and tw.is_valid():
			tw.kill()
	_phase_tween = null
	_vs_tween = null
	_combo_label_tween = null
	_impact_tween = null
	_zoom_tween = null
	_ko_tween = null


# ------------------------------------------------------------ fighters

func _spawn_fighter(id: int, pos: Vector2, slug: String, ai: bool) -> void:
	var f := Fighter.new()
	f.name = "Fighter%d" % id
	f.player_id = id
	f.art_slug = slug
	# Stats, moves and skill slots all come from the generated skill config.
	f.def = SkillDb.character(slug)
	f.display_name = Art.display_name(slug)
	f.is_ai = ai
	# Give the two fighters different voices so barks do not sound doubled.
	f.voice_pitch = float(f.def.get("voice_pitch", 1.0 if id == 1 else 0.90))
	f.max_hp = SkillDb.stat(slug, "hp", 100.0)
	f.hp = f.max_hp
	f.energy = SkillDb.stat(slug, "energy_start", 60.0)
	f.position = pos
	f.main = self
	f.ground_y = GROUND_Y
	f.arena_min_x = ARENA_MIN_X
	f.arena_max_x = ARENA_MAX_X
	add_child(f)
	fighters.append(f)


func _check_ko() -> bool:
	if round_over:
		return true
	for f in fighters:
		# HP is the authoritative win condition. State.KO is normally entered by
		# take_hit immediately, but checking both keeps a zero-HP fighter from
		# leaving the round alive if another state transition happened that frame.
		if f.state == Fighter.State.KO or f.hp <= 0.0:
			if f.state != Fighter.State.KO:
				f._start_ko(Vector2.ZERO)
			_end_match(f)
			return true
	return false


func _end_match(loser: Fighter) -> void:
	round_over = true
	fight_time = 0.0
	_timer_label.text = "00"
	var winner: Fighter = fighters[0] if fighters[1] == loser else fighters[1]
	phase = "over"
	sfx.play_at("ko", loser.position + Vector2(0.0, -80.0))
	sfx.duck(9.0, 1.2)
	_play_ko_finish(loser, winner)
	# Let the KO boom and the freeze frame land before the result music.
	var timer := get_tree().create_timer(1.3)
	var result_generation := _match_generation
	timer.timeout.connect(func() -> void:
		# R/Esc may start another match before this delayed callback fires.
		# Ignore stale callbacks and freed winners from the previous round.
		if result_generation != _match_generation or not is_instance_valid(winner):
			return
		sfx.music("result_sting", -8.0, false)
		winner.say_win()
		if _menu_result_panel != null:
			var result_title := _menu_result_panel.get_child(1) as Label
			result_title.text = winner.display_name + " 获胜！"
			_menu_result_panel.visible = true
	)


func _play_ko_finish(loser: Fighter, winner: Fighter) -> void:
	# Anime finish: freeze the final blow, white impact frame, camera punch-in on
	# the loser, a big K.O. stamp, then the winner banner.
	if _vs_tween != null and _vs_tween.is_valid():
		_vs_tween.kill()
	_hide_vs_cards()

	add_hitstop(30)  # hold the impact frame while the finish plays out
	_flash_rect.color = Color(1, 1, 1, 0.95)

	_impact_tween = create_tween()
	_impact_tween.tween_property(_flash_rect, "color:a", 0.0, 0.34)

	cam.zoom = Vector2(1.6, 1.6)
	var target_x: float = clampf(loser.position.x, 320.0, 960.0)
	cam.position.x = lerpf(cam.position.x, target_x, 0.6)
	_zoom_tween = create_tween()
	_zoom_tween.tween_property(cam, "zoom", Vector2(1.22, 1.22), 0.5).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)

	_ko_label.pivot_offset = Vector2(640.0, 75.0)
	_ko_label.scale = Vector2(2.2, 2.2)
	_ko_label.modulate.a = 0.0
	var finish_generation := _match_generation
	_ko_tween = create_tween()
	_ko_tween.set_parallel(true)
	_ko_tween.tween_property(_ko_label, "modulate:a", 1.0, 0.12)
	_ko_tween.tween_property(_ko_label, "scale", Vector2(1.0, 1.0), 0.34).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	_ko_tween.chain().tween_interval(0.75)
	_ko_tween.chain().tween_property(_ko_label, "modulate:a", 0.0, 0.4)
	_ko_tween.chain().tween_callback(func() -> void:
		if finish_generation != _match_generation or not is_instance_valid(winner) or _ko_label == null:
			return
		_show_phase_text(winner.display_name + " WINS!")
	)


func _time_up() -> void:
	if round_over:
		return
	round_over = true
	phase = "over"
	sfx.play("time_up")
	sfx.duck(6.0, 1.0)
	var a := fighters[0].hp
	var b := fighters[1].hp
	if a > b:
		_show_phase_text("TIME UP!  SORA WINS!")
		fighters[0].say_win()
	elif b > a:
		_show_phase_text("TIME UP!  KAZE WINS!")
		fighters[1].say_win()
	else:
		_show_phase_text("TIME UP!  DRAW")
	var timer := get_tree().create_timer(1.4)
	timer.timeout.connect(func() -> void:
		sfx.music("result_sting", -8.0, false)
	)


# ---------------------------------------------------------- game events

func frozen() -> bool:
	return paused or Engine.get_physics_frames() < freeze_until


func _toggle_pause() -> void:
	paused = not paused
	if _pause_overlay == null:
		return
	_pause_overlay.visible = paused
	_pause_label.visible = paused
	_pause_hint.visible = paused
	if paused:
		_pause_label.modulate.a = 0.0
		_pause_hint.modulate.a = 0.0
		var tw := create_tween()
		tw.set_parallel(true)
		tw.tween_property(_pause_label, "modulate:a", 1.0, 0.14)
		tw.tween_property(_pause_hint, "modulate:a", 1.0, 0.22)
		sfx.set_paused(true)
	else:
		sfx.set_paused(false)


func add_hitstop(frames: int) -> void:
	freeze_until = maxi(freeze_until, Engine.get_physics_frames() + frames)


func on_hit_landed(victim: Fighter, attacker, hit_pos: Vector2, dmg: float, air_hit: bool,
		kind := "", hitstop_f := -1, impact_color: Variant = null) -> void:
	if kind.is_empty():
		# No caller-supplied grading: fall back to how hard it hit.
		if dmg >= 10.0:
			kind = "hit_heavy"
		elif dmg >= 8.0:
			kind = "hit_medium"
		else:
			kind = "hit_light"
	var heavy := kind in ["hit_heavy", "launcher", "chakra_hit"]
	add_hitstop(hitstop_f if hitstop_f > 0 else (6 if heavy else (5 if air_hit else 4)))
	trauma = minf(1.0, trauma + (0.45 if heavy else (0.38 if air_hit else 0.3)))
	sfx.play_at(kind, hit_pos)
	var c := _resolve_hit_color(kind, impact_color, air_hit)
	spawn_fx(hit_pos, c, 30.0)
	_spawn_damage_number(hit_pos, dmg)
	if attacker != null:
		if _combo_owner == attacker:
			_combo_count += 1
		else:
			_combo_owner = attacker
			_combo_count = 1
		_combo_timer = 1.3
		_show_combo(_combo_count, attacker)


func _resolve_hit_color(kind: String, configured: Variant, air_hit: bool) -> Color:
	if configured is Array and configured.size() == 3:
		return Color(float(configured[0]), float(configured[1]), float(configured[2]))
	if kind == "chakra_hit":
		return Color(0.55, 0.9, 1.0)
	return Color(1.0, 0.85, 0.4) if air_hit else Color(1.0, 0.68, 0.3)


func on_blocked(victim: Fighter, attacker, hit_pos: Vector2) -> void:
	add_hitstop(2)
	trauma = minf(1.0, trauma + 0.08)
	sfx.play_at("block", hit_pos)
	spawn_fx(hit_pos + Vector2(attacker.facing * 18.0, 0), Color(0.5, 0.95, 1.0), 18.0)


func on_ko(victim: Fighter) -> void:
	trauma = minf(1.0, trauma + 0.5)
	spawn_fx(victim.position + Vector2(0, -70), Color(1.0, 0.5, 0.2), 46.0)


func spawn_orb(shooter: Fighter, move: Dictionary) -> void:
	var orb := Orb.new()
	orb.setup(shooter, self, move.get("projectile", {}))
	add_child(orb)
	orbs.append(orb)
	var shot_sfx := String(move.get("projectile", {}).get("spawn_sfx", "chakra_shoot"))
	sfx.play_at(shot_sfx, shooter.position + Vector2(shooter.facing * 48.0, -80.0))


func spawn_fx(pos: Vector2, color: Color, radius: float) -> void:
	var fx := FxPop.new()
	fx.setup(pos, color, radius)
	add_child(fx)


# --------------------------------------------------------------- HUD

func _build_hud() -> void:
	hud = CanvasLayer.new()
	hud.layer = 10
	add_child(hud)

	# A compact broadcast-style frame makes the arena read as a finished game
	# instead of a debug scene: title ribbon, round marker and a readable control
	# strip stay visible while the fight itself remains unobstructed.
	var top_rule := ColorRect.new()
	top_rule.color = Color(0.05, 0.04, 0.1, 0.72)
	top_rule.position = Vector2(0, 0)
	top_rule.size = Vector2(1280, 82)
	top_rule.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hud.add_child(top_rule)
	var bottom_rule := ColorRect.new()
	bottom_rule.color = Color(0.03, 0.025, 0.07, 0.84)
	bottom_rule.position = Vector2(0, 656)
	bottom_rule.size = Vector2(1280, 64)
	bottom_rule.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hud.add_child(bottom_rule)
	_label("NINJA STORM ARENA", 430, 4, 420, 25, 16, HORIZONTAL_ALIGNMENT_CENTER, Color(1.0, 0.78, 0.34))
	_label("ROUND 1  •  SHINOBI CLASH", 430, 24, 420, 22, 13, HORIZONTAL_ALIGNMENT_CENTER, Color(0.75, 0.82, 0.96, 0.9))

	# anime-style portrait plates + life/chakra bars
	_make_portrait(1, 18, 26, 62, fighters[0].art_slug)
	_make_portrait(2, 1280 - 18 - 62, 26, 62, fighters[1].art_slug)
	_make_bar(1, 92, 34, 250, 18, Color(0.08, 0.07, 0.14, 0.85), Color(0.3, 0.9, 0.35))
	_make_bar(1, 92, 58, 176, 9, Color(0.08, 0.07, 0.14, 0.85), Color(0.35, 0.85, 1.0))
	_make_bar(2, 1280 - 92 - 250, 34, 250, 18, Color(0.08, 0.07, 0.14, 0.85), Color(0.3, 0.9, 0.35))
	_make_bar(2, 1280 - 92 - 176, 58, 176, 9, Color(0.08, 0.07, 0.14, 0.85), Color(0.35, 0.85, 1.0))

	_p1_name_label = _label(fighters[0].display_name, 92, 6, 220, 26, 20, HORIZONTAL_ALIGNMENT_LEFT, Color(0.8, 0.92, 1.0))
	_p2_name_label = _label(fighters[1].display_name + ("  [CPU]" if fighters[1].is_ai else "  [P2]"), 968, 6, 220, 26, 20, HORIZONTAL_ALIGNMENT_RIGHT, Color(0.86, 1.0, 0.84))

	_timer_label = _label("99", 1280 / 2 - 70, 4, 140, 42, 32, HORIZONTAL_ALIGNMENT_CENTER, Color(1, 1, 1))
	_phase_label = _label("", 0, 250, 1280, 110, 62, HORIZONTAL_ALIGNMENT_CENTER, Color(1, 0.95, 0.85))
	_ko_label = _label("K.O.", 0, 236, 1280, 150, 118, HORIZONTAL_ALIGNMENT_CENTER, Color(1, 0.94, 0.9))
	_ko_label.modulate.a = 0.0
	_combo_label = _label("", 110, 196, 400, 60, 40, HORIZONTAL_ALIGNMENT_CENTER, Color(1, 0.86, 0.4))
	_combo_label.modulate.a = 0.0
	_hint_label = _label(
		"P1  WASD 移动   J 普攻   K 忍术   U 奥义   Q 替身        P2  方向键   , 普攻   . 忍术   K 奥义   Shift 替身",
		0, 661, 1280, 24, 13, HORIZONTAL_ALIGNMENT_CENTER, Color(0.92, 0.94, 1.0, 0.9)
	)
	_label("P 暂停   F2 CPU/双人   R 再战   M 静音   ESC 退出", 0, 687, 1280, 20, 12,
		HORIZONTAL_ALIGNMENT_CENTER, Color(0.62, 0.7, 0.85, 0.9))

	_pause_overlay = ColorRect.new()
	_pause_overlay.color = Color(0.015, 0.012, 0.04, 0.78)
	_pause_overlay.position = Vector2.ZERO
	_pause_overlay.size = Vector2(1280, 720)
	_pause_overlay.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_pause_overlay.visible = false
	hud.add_child(_pause_overlay)
	_pause_label = _label("PAUSED", 0, 248, 1280, 84, 68, HORIZONTAL_ALIGNMENT_CENTER, Color(0.92, 0.96, 1.0))
	_pause_hint = _label("按 P 继续", 0, 334, 1280, 42, 24, HORIZONTAL_ALIGNMENT_CENTER, Color(0.72, 0.86, 1.0))
	_pause_label.visible = false
	_pause_hint.visible = false

	# full-screen white flash used for impacts and the KO freeze
	_flash_rect = ColorRect.new()
	_flash_rect.color = Color(1, 1, 1, 0.0)
	_flash_rect.size = Vector2(1280, 720)
	_flash_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hud.add_child(_flash_rect)

	# versus cards that slide in during the intro
	_build_vs_cards()


func _make_portrait(player: int, x: float, y: float, size: float, slug: String) -> void:
	var frame := ColorRect.new()
	frame.color = Color(0.07, 0.06, 0.12, 0.9)
	frame.position = Vector2(x - 3.0, y - 3.0)
	frame.size = Vector2(size + 6.0, size + 6.0)
	hud.add_child(frame)
	var edge := ColorRect.new()
	edge.color = Color(0.55, 0.65, 0.8, 0.55) if player == 1 else Color(0.6, 0.85, 0.6, 0.55)
	edge.position = Vector2(x - 1.0, y - 1.0)
	edge.size = Vector2(size + 2.0, size + 2.0)
	hud.add_child(edge)
	var tex := Art.portrait_texture(slug)
	if tex != null:
		var tr := TextureRect.new()
		tr.texture = tex
		# `size` alone does not shrink a TextureRect: with the default
		# EXPAND_KEEP_SIZE its minimum size *is* the texture, so a 640x640
		# portrait stayed 640x640 however small the box was asked to be - two
		# of them covered the whole arena and the fight played out behind the
		# two plates. IGNORE_SIZE is what makes the box authoritative.
		tr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		tr.position = Vector2(x, y)
		tr.size = Vector2(size, size)
		tr.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
		tr.clip_contents = true
		hud.add_child(tr)
		_portrait[player] = tr


func _make_bar(player: int, x: float, y: float, w: float, h: float, bg_color: Color, fill_color: Color) -> void:
	var bg := ColorRect.new()
	bg.color = bg_color
	bg.position = Vector2(x, y)
	bg.size = Vector2(w, h)
	hud.add_child(bg)
	var fill := ColorRect.new()
	fill.color = fill_color
	fill.position = Vector2(x, y)
	fill.size = Vector2(w, h)
	hud.add_child(fill)
	var kind := "hp" if h > 10.0 else "energy"
	_bars["%d_%s" % [player, kind]] = {"bg": bg, "fill": fill, "x": x, "w": w, "right": player == 2}


func _label(text: String, x: float, y: float, w: float, h: float, size: int, align: int, color: Color) -> Label:
	var l := Label.new()
	l.text = text
	l.position = Vector2(x, y)
	l.size = Vector2(w, h)
	l.horizontal_alignment = align
	l.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	l.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.75))
	l.add_theme_constant_override("outline_size", 4)
	hud.add_child(l)
	return l


func _update_hud() -> void:
	for f in fighters:
		_set_bar(f.player_id, "hp", f.hp / f.max_hp)
		_set_bar(f.player_id, "energy", f.energy / maxf(1.0, SkillDb.stat(f.art_slug, "energy_max", 100.0)))


func _set_bar(player: int, kind: String, ratio: float) -> void:
	var key := "%d_%s" % [player, kind]
	if not _bars.has(key):
		return
	var data: Dictionary = _bars[key]
	var r := clampf(ratio, 0.0, 1.0)
	var fill: ColorRect = data["fill"]
	var w: float = data["w"]
	var x: float = data["x"]
	fill.size.x = w * r
	if data["right"]:
		fill.position.x = x + w * (1.0 - r)
	if kind == "hp":
		fill.color = Color.from_hsv(clampf(r * 0.33, 0.0, 0.33), 0.85, 0.95)
	else:
		fill.color = Color(0.45, 0.9, 1.0, 0.95)


func _show_phase_text(text: String) -> void:
	_phase_label.text = text
	_phase_label.modulate.a = 1.0
	if _phase_tween != null and _phase_tween.is_valid():
		_phase_tween.kill()
	_phase_tween = create_tween()
	_phase_label.pivot_offset = Vector2(640.0, 55.0)
	_phase_label.scale = Vector2(1.35, 1.35)
	_phase_tween.tween_property(_phase_label, "scale", Vector2(1.0, 1.0), 0.22).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	_phase_tween.tween_interval(0.7)
	_phase_tween.tween_property(_phase_label, "modulate:a", 0.0, 0.45)


# ------------------------------------------------------------ versus intro

func _build_vs_cards() -> void:
	_vs_left = _vs_card(Art.portrait_texture("sora"), -360.0, 150.0)
	_vs_right = _vs_card(Art.portrait_texture("kaze"), 1280.0 + 40.0, 150.0)


func _vs_card(tex: Texture2D, x: float, y: float) -> TextureRect:
	var panel := ColorRect.new()
	panel.color = Color(0.06, 0.05, 0.11, 0.0)
	panel.position = Vector2(x - 8.0, y - 8.0)
	panel.size = Vector2(336.0, 416.0)
	hud.add_child(panel)
	var tr := TextureRect.new()
	tr.texture = tex
	# Same trap as the HUD portrait above: without this the card draws at the
	# portrait's own 640x640 and the 336x416 panel behind it lines up with
	# nothing.
	tr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	tr.position = Vector2(x, y)
	tr.size = Vector2(320.0, 400.0)
	tr.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	tr.clip_contents = true
	tr.modulate.a = 0.0
	hud.add_child(tr)
	tr.set_meta("panel", panel)
	return tr


func _play_intro() -> void:
	if _vs_left == null or _vs_right == null:
		return
	var panel_l: ColorRect = _vs_left.get_meta("panel")
	var panel_r: ColorRect = _vs_right.get_meta("panel")
	if _vs_tween != null and _vs_tween.is_valid():
		_vs_tween.kill()
	_vs_tween = create_tween()
	_vs_tween.set_parallel(true)
	_vs_tween.tween_property(_vs_left, "position:x", 48.0, 0.45).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_vs_tween.tween_property(_vs_left, "modulate:a", 0.75, 0.45)
	_vs_tween.tween_property(panel_l, "position:x", 40.0, 0.45).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_vs_tween.tween_property(panel_l, "color:a", 0.55, 0.45)
	_vs_tween.tween_property(_vs_right, "position:x", 912.0, 0.45).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_vs_tween.tween_property(_vs_right, "modulate:a", 0.75, 0.45)
	_vs_tween.tween_property(panel_r, "position:x", 904.0, 0.45).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_vs_tween.tween_property(panel_r, "color:a", 0.55, 0.45)


func _play_intro_out() -> void:
	if _vs_left == null or _vs_right == null:
		return
	if _intro_out_done:
		return
	_intro_out_done = true
	var panel_l: ColorRect = _vs_left.get_meta("panel")
	var panel_r: ColorRect = _vs_right.get_meta("panel")
	if _vs_tween != null and _vs_tween.is_valid():
		_vs_tween.kill()
	_flash_rect.color = Color(1, 1, 1, 0.55)
	var fade := create_tween()
	fade.tween_property(_flash_rect, "color:a", 0.0, 0.3)
	_vs_tween = create_tween()
	_vs_tween.set_parallel(true)
	_vs_tween.tween_property(_vs_left, "position:x", -360.0, INTRO_OUT_TIME).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_IN)
	_vs_tween.tween_property(_vs_left, "modulate:a", 0.0, INTRO_OUT_TIME)
	_vs_tween.tween_property(panel_l, "position:x", -368.0, INTRO_OUT_TIME)
	_vs_tween.tween_property(panel_l, "color:a", 0.0, INTRO_OUT_TIME)
	_vs_tween.tween_property(_vs_right, "position:x", 1280.0 + 40.0, INTRO_OUT_TIME).set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_IN)
	_vs_tween.tween_property(_vs_right, "modulate:a", 0.0, INTRO_OUT_TIME)
	_vs_tween.tween_property(panel_r, "position:x", 1280.0 + 32.0, INTRO_OUT_TIME)
	_vs_tween.tween_property(panel_r, "color:a", 0.0, INTRO_OUT_TIME)
	# Sliding off-screen is not enough on its own: if a tween ever gets killed
	# or interrupted half-way the card would stay on the arena for the whole
	# match, so drop the nodes once the slide is done.
	_vs_tween.chain().tween_callback(_hide_vs_cards)


func _hide_vs_cards() -> void:
	for card in [_vs_left, _vs_right]:
		if card == null:
			continue
		card.visible = false
		var panel = card.get_meta("panel")
		if panel != null:
			panel.visible = false


func _show_combo(count: int, attacker) -> void:
	if count < 2:
		return
	_combo_label.text = "%d HIT COMBO" % count
	_combo_label.position.x = 110.0 if attacker == fighters[0] else 770.0
	_combo_label.pivot_offset = Vector2(200.0, 30.0)
	if _combo_label_tween != null and _combo_label_tween.is_valid():
		_combo_label_tween.kill()
	_combo_label_tween = create_tween()
	_combo_label_tween.tween_property(_combo_label, "modulate:a", 1.0, 0.06)
	_combo_label_tween.parallel().tween_property(_combo_label, "scale", Vector2(1.0, 1.0), 0.18).from(Vector2(1.5, 1.5)).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	_combo_label_tween.tween_interval(0.55)
	_combo_label_tween.tween_property(_combo_label, "modulate:a", 0.0, 0.3)


func _spawn_damage_number(pos: Vector2, dmg: float) -> void:
	var pop := DamagePop.new()
	pop.setup(pos + Vector2(0, -74), int(dmg))
	add_child(pop)


func _update_shake(delta: float) -> void:
	trauma = maxf(0.0, trauma - delta * 1.6)
	var s := pow(trauma, 2.0) * 28.0
	# Skip the work entirely while the screen is settled, which is most of the
	# match: this runs on every rendered frame and used to allocate a Vector2
	# and burn randomness even when there was nothing to shake.
	cam.offset = Vector2.ZERO if s <= 0.0 else Vector2(
		_shake_rng.randf_range(-1.0, 1.0), _shake_rng.randf_range(-1.0, 1.0)) * s


func _update_aura() -> void:
	# The chakra flight hum is one looping player that follows whoever is flying;
	# two fighters in the air share it rather than stacking two drones.
	var flying: Fighter = null
	for f in fighters:
		if f.is_flying():
			flying = f
			break
	if flying == null:
		sfx.aura(false)
		return
	sfx.aura(true, flying.position + Vector2(0.0, -80.0))
