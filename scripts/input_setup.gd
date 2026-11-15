class_name InputSetup

# All input actions are created here in code instead of project.godot,
# which makes the prototype easy to extend and re-map later.
func setup() -> void:
	_key_action("p1_left", [KEY_A])
	_key_action("p1_right", [KEY_D])
	_key_action("p1_jump", [KEY_W])
	_key_action("p1_block", [KEY_S])
	_key_action("p1_melee", [KEY_J])
	_key_action("p1_proj", [KEY_K])       # 忍术（jutsu 槽）
	_key_action("p1_skill1", [KEY_L])     # 技能槽 1
	_key_action("p1_skill2", [KEY_I])     # 技能槽 2
	_key_action("p1_substitute", [KEY_Q])
	_key_action("p1_ultimate", [KEY_U])

	# P2 keyboard: arrows + bottom-row keys (works on laptops without numpad)
	_key_action("p2_left", [KEY_LEFT])
	_key_action("p2_right", [KEY_RIGHT])
	_key_action("p2_jump", [KEY_UP])
	_key_action("p2_block", [KEY_DOWN])
	_key_action("p2_melee", [KEY_COMMA])
	_key_action("p2_proj", [KEY_PERIOD])
	_key_action("p2_skill1", [KEY_SLASH])
	_key_action("p2_skill2", [KEY_SEMICOLON])
	_key_action("p2_substitute", [KEY_SHIFT])
	_key_action("p2_ultimate", [KEY_K])

	_key_action("rematch", [KEY_R])
	_key_action("pause", [KEY_P])
	_key_action("toggle_cpu", [KEY_F2])
	_key_action("mute", [KEY_M])
	_key_action("quit", [KEY_ESCAPE])

	_pad_action("mute", 0, JOY_BUTTON_BACK, -1, 0.0)

	# Gamepads: P1 is the first controller, P2 the second one.
	_pad_action("p1_left", 0, JOY_BUTTON_DPAD_LEFT, JOY_AXIS_LEFT_X, -1.0)
	_pad_action("p1_right", 0, JOY_BUTTON_DPAD_RIGHT, JOY_AXIS_LEFT_X, 1.0)
	_pad_action("p1_jump", 0, JOY_BUTTON_X, JOY_AXIS_LEFT_Y, -1.0)
	_pad_action("p1_block", 0, JOY_BUTTON_Y, JOY_AXIS_LEFT_Y, 1.0)
	_pad_action("p1_melee", 0, JOY_BUTTON_A, -1, 0.0)
	_pad_action("p1_proj", 0, JOY_BUTTON_B, -1, 0.0)
	_pad_action("p1_skill1", 0, JOY_BUTTON_LEFT_SHOULDER, -1, 0.0)
	_pad_action("p1_skill2", 0, JOY_BUTTON_RIGHT_SHOULDER, -1, 0.0)

	_pad_action("p2_left", 1, JOY_BUTTON_DPAD_LEFT, JOY_AXIS_LEFT_X, -1.0)
	_pad_action("p2_right", 1, JOY_BUTTON_DPAD_RIGHT, JOY_AXIS_LEFT_X, 1.0)
	_pad_action("p2_jump", 1, JOY_BUTTON_X, JOY_AXIS_LEFT_Y, -1.0)
	_pad_action("p2_block", 1, JOY_BUTTON_Y, JOY_AXIS_LEFT_Y, 1.0)
	_pad_action("p2_melee", 1, JOY_BUTTON_A, -1, 0.0)
	_pad_action("p2_proj", 1, JOY_BUTTON_B, -1, 0.0)
	_pad_action("p2_skill1", 1, JOY_BUTTON_LEFT_SHOULDER, -1, 0.0)
	_pad_action("p2_skill2", 1, JOY_BUTTON_RIGHT_SHOULDER, -1, 0.0)


static func _key_action(action: StringName, keys: Array) -> void:
	if not InputMap.has_action(action):
		InputMap.add_action(action)
	for code in keys:
		var ev := InputEventKey.new()
		ev.physical_keycode = code
		if not InputMap.action_has_event(action, ev):
			InputMap.action_add_event(action, ev)


static func _pad_action(action: StringName, device: int, button: int, axis: int, axis_value: float) -> void:
	if not InputMap.has_action(action):
		InputMap.add_action(action)
	if button >= 0:
		var ev := InputEventJoypadButton.new()
		ev.device = device
		ev.button_index = button
		if not InputMap.action_has_event(action, ev):
			InputMap.action_add_event(action, ev)
	if axis >= 0:
		var ev2 := InputEventJoypadMotion.new()
		ev2.device = device
		ev2.axis = axis
		ev2.axis_value = axis_value
		if not InputMap.action_has_event(action, ev2):
			InputMap.action_add_event(action, ev2)
