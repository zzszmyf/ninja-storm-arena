extends SceneTree

const Main = preload("res://scripts/main.gd")

func _initialize() -> void:
	var main := Main.new()
	var configured: Color = main._resolve_hit_color("hit_heavy", [0.72, 0.2, 1.0], false)
	if not configured.is_equal_approx(Color(0.72, 0.2, 1.0)):
		push_error("FX FAIL: 招式配置的颜色应覆盖默认重击色")
		quit(1)
		return
	var fallback: Color = main._resolve_hit_color("chakra_hit", [], false)
	if not fallback.is_equal_approx(Color(0.55, 0.9, 1.0)):
		push_error("FX FAIL: 缺省颜色应保留查克拉命中特效")
		quit(1)
		return
	var air: Color = main._resolve_hit_color("hit_light", [], true)
	if not air.is_equal_approx(Color(1.0, 0.85, 0.4)):
		push_error("FX FAIL: 空中命中默认颜色应维持原表现")
		quit(1)
		return
	main.free()
	print("FX OK: per-move hit color with legacy fallbacks")
	quit(0)
