extends SceneTree

# TDD regression suite for the front-end flow.  The test talks to the same
# public transitions the menu uses, then lets the real scene process a KO and
# the result delay.  It deliberately checks user-visible state, not internals.

var _main = null
var _frame := 0
var _stage := 0
var _failed := false


func _initialize() -> void:
	change_scene_to_file("res://scenes/main.tscn")
	process_frame.connect(_tick)


func _tick() -> void:
	_frame += 1
	if _main == null:
		_main = root.get_node_or_null("Main")
		return
	match _stage:
		0:
			_check(_main.phase == "menu", "启动后进入主菜单")
			_check(_main._menu_main_panel.visible, "主菜单面板可见")
			_check(not _main._menu_select_panel.visible, "角色选择默认隐藏")
			_check(_main.fighters.is_empty(), "主菜单没有残留战斗角色")
			_main._update_main_menu_cursor()
			_main._menu_main_cursor = 1
			_main._update_main_menu_cursor()
			_main._menu_main_cursor = 0
			_main._update_main_menu_cursor()
			var option_texts: Array[String] = []
			for node in _main._menu_main_panel.get_children():
				if node is Label and (node.text.contains("开始游戏") or node.text.contains("操作说明") or node.text.contains("退出游戏")):
					option_texts.append(String(node.text))
			_check(option_texts.size() == 3, "菜单刷新后仍只有三个选项")
			_check(option_texts.filter(func(text): return text.contains("开始游戏")).size() == 1,
				"菜单刷新后开始游戏不会重复")
			_main._p1_slug = "kaze"
			_main._p2_slug = "sora"
			_main._cpu_enabled = true
			_main._start_match(_main._p1_slug, _main._p2_slug)
			_stage = 1
		1:
			_check(_main.phase == "ready" or _main.phase == "fight", "选择角色后进入开场阶段")
			_check(_main.fighters.size() == 2, "开局创建两名角色")
			_check(_main.fighters[0].art_slug == "kaze", "P1 角色选择生效")
			_check(_main.fighters[1].art_slug == "sora", "P2 角色选择生效")
			_check(_main._p1_name_label.text == "KAZE", "左侧 HUD 显示用户选择的角色")
			_check(_main._p2_name_label.text.begins_with("SORA"), "右侧 HUD 显示对手选择的角色")
			if _main.phase == "fight":
				_main.fighters[0].hp = 0.0
				_stage = 2
		2:
			if _main.phase == "over":
				_stage = 3
		3:
			if not _main._menu_result_panel.visible:
				return
			_check(_main._menu_result_panel.visible, "KO 后显示结算面板")
			_main._start_match("sora", "kaze")
			_check(_main.phase == "ready", "重新开始回到开场阶段")
			_check(_main.fighters.size() == 2, "重新开始不会叠加角色")
			_main._show_main_menu()
			_stage = 4
		4:
			_check(_main.phase == "menu", "Esc 返回主菜单")
			_check(_main._menu_main_panel.visible, "返回后主菜单可见")
			_check(_main.fighters.is_empty(), "返回主菜单清理战斗角色")
			_report()
			quit(0 if not _failed else 1)

	if _frame > 600:
		_fail("菜单流程超时")


func _check(ok: bool, label: String) -> void:
	if ok:
		return
	_fail(label)


func _fail(label: String) -> void:
	_failed = true
	print("MENU FAIL: " + label)


func _report() -> void:
	if not _failed:
		print("MENU OK: menu -> select -> fight -> KO -> rematch -> menu")
