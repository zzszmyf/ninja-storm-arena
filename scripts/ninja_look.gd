class_name NinjaLook
extends RefCounted

# Anime-style, cel-shaded character rendering, drawn entirely with code.
#
# Coordinate space: origin sits at the fighter's feet, -Y points up.
# The pose dictionary is built from the gameplay state (see build_pose) and
# this file only cares about turning that skeleton into ink-lined artwork.
#
# Skeleton keys (all Vector2, in local space):
#   hip, chest, head, sh_f, sh_b, el_f, el_b, hand_f, hand_b,
#   knee_f, knee_b, foot_f, foot_b
# Extra keys:
#   face ("calm"/"strain"/"hurt"/"ko"), fist_f, fist_b (bool),
#   aura (0..1), seal (0..1 hand-seal -> thrust), scarf (0..1 flutter),
#   band (0..1 headband tail lift), air (0..1 airborne blend), down (bool lying)

const OUTLINE := Color("#181322")
const OUTLINE_W := 3.0
const MESH := Color("#39404e")


# ------------------------------------------------------------ pose building

static func build_pose(kind: String, k: Dictionary, t: float) -> Dictionary:
	var p: Dictionary = _idle_pose(t)
	match kind:
		"run":
			_run_pose(p, t)
		"air":
			_air_pose(p, k)
		"fly":
			_fly_pose(p, t)
		"attack":
			_attack_pose(p, k)
		"proj":
			_proj_pose(p, k, t)
		"block":
			_block_pose(p, t)
		"hurt":
			_hurt_pose(p, k, t)
		"ko":
			_ko_pose(p, k, t)
		_:
			pass
	if bool(k.get("flying", false)):
		p["aura"] = 1.0
	return p


static func _idle_pose(t: float) -> Dictionary:
	var breath: float = sin(t * 2.4) * 1.6
	var sway: float = sin(t * 2.4 + 0.6) * 1.2
	return {
		"hip": Vector2(0.0, -62.0 - breath * 0.4),
		"chest": Vector2(1.0 + sway * 0.3, -104.0 - breath),
		"head": Vector2(2.0 + sway * 0.6, -128.0 - breath * 1.2),
		"sh_f": Vector2(9.0, -101.0 - breath),
		"sh_b": Vector2(-7.0, -100.0 - breath * 0.8),
		"el_f": Vector2(17.0, -86.0 - breath),
		"el_b": Vector2(-14.0, -84.0 - breath * 0.8),
		"hand_f": Vector2(21.0 + sway, -72.0 - breath),
		"hand_b": Vector2(-19.0 + sway * 0.5, -70.0 - breath * 0.8),
		"knee_f": Vector2(11.0, -32.0),
		"knee_b": Vector2(-11.0, -31.0),
		"foot_f": Vector2(13.0, 0.0),
		"foot_b": Vector2(-13.0, 0.0),
		"face": "calm",
		"fist_f": false,
		"fist_b": false,
		"aura": 0.0,
		"seal": 0.0,
		"scarf": 0.0,
		"band": 0.0,
		"air": 0.0,
		"down": false,
	}


static func _run_pose(p: Dictionary, t: float) -> void:
	var cyc: float = t * 12.0
	var s: float = sin(cyc)
	var c: float = cos(cyc)
	var lean: float = 7.0
	p["hip"] = Vector2(0.0, -60.0 + absf(c) * 2.0)
	p["chest"] = Vector2(lean * 0.6, -102.0 + absf(c) * 2.0)
	p["head"] = Vector2(lean, -126.0 + absf(c) * 2.0)
	p["sh_f"] = Vector2(9.0 + lean * 0.4, -99.0 + absf(c) * 2.0)
	p["sh_b"] = Vector2(-7.0 + lean * 0.4, -98.0 + absf(c) * 2.0)
	# legs: alternate stride, lifted leg folds at the knee
	var lift_f: float = maxf(0.0, s) * 16.0
	var lift_b: float = maxf(0.0, -s) * 16.0
	p["knee_f"] = Vector2(9.0 + s * 16.0, -34.0 - lift_f * 0.8)
	p["foot_f"] = Vector2(13.0 + s * 26.0, -lift_f)
	p["knee_b"] = Vector2(-9.0 - s * 16.0, -33.0 - lift_b * 0.8)
	p["foot_b"] = Vector2(-13.0 - s * 26.0, -lift_b)
	# arms counter-swing, elbows bent like a runner
	p["el_f"] = Vector2(6.0 - s * 12.0, -88.0)
	p["hand_f"] = Vector2(-2.0 - s * 20.0, -78.0 + s * 8.0)
	p["el_b"] = Vector2(-6.0 + s * 12.0, -86.0)
	p["hand_b"] = Vector2(-14.0 + s * 20.0, -76.0 - s * 8.0)
	p["fist_f"] = true
	p["fist_b"] = true
	p["face"] = "calm"


static func _air_pose(p: Dictionary, k: Dictionary) -> void:
	var vy: float = float(k.get("vy", 0.0))
	var rising: bool = vy < -60.0
	p["hip"] = Vector2(0.0, -60.0)
	p["chest"] = Vector2(2.0, -102.0)
	p["head"] = Vector2(4.0, -126.0)
	p["sh_f"] = Vector2(10.0, -100.0)
	p["sh_b"] = Vector2(-6.0, -99.0)
	if rising:
		p["el_f"] = Vector2(16.0, -112.0)
		p["hand_f"] = Vector2(14.0, -128.0)
		p["el_b"] = Vector2(-14.0, -110.0)
		p["hand_b"] = Vector2(-18.0, -126.0)
		p["knee_f"] = Vector2(12.0, -44.0)
		p["foot_f"] = Vector2(18.0, -24.0)
		p["knee_b"] = Vector2(-10.0, -40.0)
		p["foot_b"] = Vector2(-8.0, -18.0)
	else:
		p["el_f"] = Vector2(20.0, -92.0)
		p["hand_f"] = Vector2(24.0, -104.0)
		p["el_b"] = Vector2(-18.0, -90.0)
		p["hand_b"] = Vector2(-26.0, -100.0)
		p["knee_f"] = Vector2(14.0, -40.0)
		p["foot_f"] = Vector2(20.0, -20.0)
		p["knee_b"] = Vector2(-12.0, -46.0)
		p["foot_b"] = Vector2(-14.0, -26.0)
	p["air"] = 1.0
	p["face"] = "calm"


static func _fly_pose(p: Dictionary, t: float) -> void:
	var flutter: float = sin(t * 16.0) * 3.0
	p["hip"] = Vector2(-4.0, -62.0)
	p["chest"] = Vector2(2.0, -100.0)
	p["head"] = Vector2(10.0, -122.0)
	p["sh_f"] = Vector2(10.0, -97.0)
	p["sh_b"] = Vector2(-4.0, -98.0)
	p["el_f"] = Vector2(-2.0, -86.0)
	p["hand_f"] = Vector2(-18.0, -74.0 + flutter * 0.4)
	p["el_b"] = Vector2(-12.0, -84.0)
	p["hand_b"] = Vector2(-26.0, -70.0 - flutter * 0.4)
	p["knee_f"] = Vector2(-6.0, -38.0)
	p["foot_f"] = Vector2(-26.0, -18.0 + flutter)
	p["knee_b"] = Vector2(-14.0, -42.0)
	p["foot_b"] = Vector2(-32.0, -26.0 - flutter)
	p["aura"] = 1.0
	p["scarf"] = 1.0
	p["band"] = 1.0
	p["face"] = "strain"


static func _attack_pose(p: Dictionary, k: Dictionary) -> void:
	var step: int = int(k.get("step", 0))
	var atk_t: float = float(k.get("atk_t", 0.0))
	var startup: float = maxf(float(k.get("startup", 0.08)), 0.001)
	var air: bool = bool(k.get("air", false))
	var ext: float = clampf(atk_t / startup, 0.0, 1.0)
	if air:
		p["hip"] = Vector2(0.0, -60.0)
		p["chest"] = Vector2(4.0, -100.0)
		p["head"] = Vector2(8.0, -124.0)
		p["sh_f"] = Vector2(12.0, -98.0)
		p["sh_b"] = Vector2(-6.0, -98.0)
		p["el_f"] = Vector2(20.0 + ext * 14.0, -96.0)
		p["hand_f"] = Vector2(26.0 + ext * 34.0, -88.0)
		p["el_b"] = Vector2(-12.0, -94.0)
		p["hand_b"] = Vector2(-18.0, -108.0)
		p["knee_f"] = Vector2(10.0, -38.0)
		p["foot_f"] = Vector2(16.0, -16.0)
		p["knee_b"] = Vector2(-14.0, -44.0)
		p["foot_b"] = Vector2(-18.0, -24.0)
		p["fist_f"] = true
		p["face"] = "strain"
		p["air"] = 1.0
		return

	p["face"] = "strain"
	p["scarf"] = 0.6
	match step:
		1:
			# hook: torso rotates, lead arm sweeps across the body
			p["hip"] = Vector2(2.0, -60.0)
			p["chest"] = Vector2(7.0, -102.0)
			p["head"] = Vector2(9.0, -126.0)
			p["sh_f"] = Vector2(14.0, -100.0)
			p["sh_b"] = Vector2(-2.0, -100.0)
			p["el_f"] = Vector2(20.0 + ext * 10.0, -98.0)
			p["hand_f"] = Vector2(30.0 + ext * 26.0, -108.0 - ext * 10.0)
			p["el_b"] = Vector2(-12.0, -86.0)
			p["hand_b"] = Vector2(-8.0, -74.0)
			p["knee_f"] = Vector2(18.0, -34.0)
			p["foot_f"] = Vector2(26.0, 0.0)
			p["knee_b"] = Vector2(-14.0, -32.0)
			p["foot_b"] = Vector2(-20.0, 0.0)
			p["fist_f"] = true
			p["fist_b"] = true
		2:
			# finisher: spinning roundhouse kick, body leans away
			p["hip"] = Vector2(-2.0, -58.0)
			p["chest"] = Vector2(-8.0, -102.0)
			p["head"] = Vector2(-10.0, -128.0)
			p["sh_f"] = Vector2(-2.0, -100.0)
			p["sh_b"] = Vector2(-14.0, -98.0)
			p["el_f"] = Vector2(-16.0, -92.0)
			p["hand_f"] = Vector2(-28.0, -82.0)
			p["el_b"] = Vector2(-24.0, -84.0)
			p["hand_b"] = Vector2(-34.0, -70.0)
			p["knee_f"] = Vector2(16.0 + ext * 12.0, -58.0 - ext * 6.0)
			p["foot_f"] = Vector2(26.0 + ext * 34.0, -70.0 - ext * 10.0)
			p["knee_b"] = Vector2(-6.0, -32.0)
			p["foot_b"] = Vector2(-10.0, 0.0)
			p["fist_f"] = false
			p["fist_b"] = true
		_:
			# jab: straight lead punch with the body driving forward
			p["hip"] = Vector2(2.0, -60.0)
			p["chest"] = Vector2(8.0, -102.0)
			p["head"] = Vector2(11.0, -125.0)
			p["sh_f"] = Vector2(14.0, -100.0)
			p["sh_b"] = Vector2(-4.0, -100.0)
			p["el_f"] = Vector2(22.0 + ext * 20.0, -99.0)
			p["hand_f"] = Vector2(28.0 + ext * 32.0, -99.0)
			p["el_b"] = Vector2(-10.0, -88.0)
			p["hand_b"] = Vector2(-2.0, -80.0)
			p["knee_f"] = Vector2(16.0, -34.0)
			p["foot_f"] = Vector2(24.0, 0.0)
			p["knee_b"] = Vector2(-14.0, -32.0)
			p["foot_b"] = Vector2(-22.0, 0.0)
			p["fist_f"] = true
			p["fist_b"] = true


static func _proj_pose(p: Dictionary, k: Dictionary, t: float) -> void:
	var proj_t: float = float(k.get("proj_t", 0.0))
	# 0.0-0.08s: hand seal at the chest, then thrust both palms forward.
	var thrust: float = clampf((proj_t - 0.05) / 0.09, 0.0, 1.0)
	var seal: Vector2 = Vector2(14.0, -96.0)
	var thrust_f: Vector2 = Vector2(34.0, -94.0)
	var thrust_b: Vector2 = Vector2(28.0, -86.0)
	p["hip"] = Vector2(1.0, -60.0)
	p["chest"] = Vector2(3.0 + thrust * 5.0, -102.0)
	p["head"] = Vector2(5.0 + thrust * 6.0, -126.0)
	p["sh_f"] = Vector2(10.0, -100.0)
	p["sh_b"] = Vector2(-6.0, -100.0)
	p["el_f"] = seal.lerp(Vector2(24.0, -98.0), thrust)
	p["hand_f"] = seal.lerp(thrust_f, thrust)
	p["el_b"] = Vector2(-2.0, -92.0).lerp(Vector2(18.0, -92.0), thrust)
	p["hand_b"] = Vector2(6.0, -98.0).lerp(thrust_b, thrust)
	p["knee_f"] = Vector2(15.0, -34.0)
	p["foot_f"] = Vector2(22.0, 0.0)
	p["knee_b"] = Vector2(-14.0, -32.0)
	p["foot_b"] = Vector2(-20.0, 0.0)
	p["seal"] = 1.0 - thrust
	p["face"] = "strain"
	p["scarf"] = 0.4


static func _block_pose(p: Dictionary, t: float) -> void:
	var brace: float = sin(t * 6.0) * 0.8
	p["hip"] = Vector2(-2.0, -56.0)
	p["chest"] = Vector2(-4.0, -98.0)
	p["head"] = Vector2(1.0, -122.0)
	p["sh_f"] = Vector2(6.0, -96.0)
	p["sh_b"] = Vector2(-8.0, -95.0)
	p["el_f"] = Vector2(16.0 + brace, -96.0)
	p["hand_f"] = Vector2(20.0, -114.0)
	p["el_b"] = Vector2(6.0, -92.0)
	p["hand_b"] = Vector2(14.0, -108.0)
	p["knee_f"] = Vector2(14.0, -32.0)
	p["foot_f"] = Vector2(18.0, 0.0)
	p["knee_b"] = Vector2(-16.0, -30.0)
	p["foot_b"] = Vector2(-24.0, 0.0)
	p["fist_f"] = true
	p["face"] = "strain"


static func _hurt_pose(p: Dictionary, k: Dictionary, t: float) -> void:
	var shake: float = sin(t * 40.0) * 1.5
	p["hip"] = Vector2(-5.0, -58.0)
	p["chest"] = Vector2(-15.0 + shake, -100.0)
	p["head"] = Vector2(-22.0 + shake, -124.0)
	p["sh_f"] = Vector2(-6.0, -98.0)
	p["sh_b"] = Vector2(-18.0, -96.0)
	p["el_f"] = Vector2(-4.0, -114.0)
	p["hand_f"] = Vector2(-10.0, -128.0)
	p["el_b"] = Vector2(-24.0, -110.0)
	p["hand_b"] = Vector2(-30.0, -122.0)
	p["knee_f"] = Vector2(12.0, -32.0)
	p["foot_f"] = Vector2(16.0, 0.0)
	p["knee_b"] = Vector2(-18.0, -30.0)
	p["foot_b"] = Vector2(-26.0, 0.0)
	p["face"] = "hurt"
	if not bool(k.get("grounded", true)):
		p["knee_f"] = Vector2(16.0, -44.0)
		p["foot_f"] = Vector2(22.0, -22.0)
		p["knee_b"] = Vector2(-16.0, -40.0)
		p["foot_b"] = Vector2(-22.0, -18.0)
		p["air"] = 1.0


static func _ko_pose(p: Dictionary, k: Dictionary, t: float) -> void:
	# Lying on their back, head trailing behind, limbs sprawled out.
	var settle: float = clampf(float(k.get("ko_t", 0.0)) * 3.0, 0.0, 1.0)
	var bounce: float = (1.0 - settle) * 6.0
	p["hip"] = Vector2(6.0, -20.0 - bounce)
	p["chest"] = Vector2(-12.0, -22.0 - bounce)
	p["head"] = Vector2(-32.0, -24.0 - bounce)
	p["sh_f"] = Vector2(-8.0, -22.0 - bounce)
	p["sh_b"] = Vector2(-16.0, -26.0 - bounce)
	p["el_f"] = Vector2(-14.0, -40.0 - bounce)
	p["hand_f"] = Vector2(-26.0, -52.0 - bounce)
	p["el_b"] = Vector2(-24.0, -14.0 - bounce)
	p["hand_b"] = Vector2(-38.0, -8.0 - bounce)
	p["knee_f"] = Vector2(26.0, -18.0)
	p["foot_f"] = Vector2(44.0, -6.0)
	p["knee_b"] = Vector2(20.0, -32.0)
	p["foot_b"] = Vector2(38.0, -28.0)
	p["face"] = "ko"
	p["down"] = true


# ------------------------------------------------------------------ drawing

static func draw_fighter(
	c: CanvasItem,
	kind: String,
	k: Dictionary,
	pal: Dictionary,
	t: float,
	facing: int,
	origin := Vector2.ZERO
) -> void:
	var p: Dictionary = build_pose(kind, k, t)
	c.draw_set_transform(origin, 0.0, Vector2(float(facing), 1.0))
	var aura: float = float(p["aura"])
	if aura > 0.01:
		_draw_aura(c, p, pal, t, aura)
	_draw_band_tail(c, p, pal, t)
	_draw_arm(c, p, pal, true, t)
	_draw_leg(c, p, pal, true)
	_draw_scarf(c, p, pal, t)
	_draw_torso(c, p, pal)
	_draw_leg(c, p, pal, false)
	_draw_head(c, p, pal, t)
	_draw_arm(c, p, pal, false, t)
	_draw_chakra(c, p, pal, t)
	c.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)


static func draw_silhouette(
	c: CanvasItem,
	kind: String,
	k: Dictionary,
	t: float,
	facing: int,
	col: Color,
	origin := Vector2.ZERO
) -> void:
	# Flat silhouette: used for afterimages and for the white hit-flash frame.
	var p: Dictionary = build_pose(kind, k, t)
	c.draw_set_transform(origin, 0.0, Vector2(float(facing), 1.0))
	c.draw_line(p["hip"], p["chest"], col, 24.0, true)
	c.draw_line(p["chest"], p["head"], col, 20.0, true)
	c.draw_circle(p["head"], 17.0, col)
	c.draw_line(p["hip"], p["knee_b"], col, 13.0, true)
	c.draw_line(p["knee_b"], p["foot_b"], col, 11.0, true)
	c.draw_line(p["hip"], p["knee_f"], col, 13.0, true)
	c.draw_line(p["knee_f"], p["foot_f"], col, 11.0, true)
	c.draw_line(p["sh_b"], p["el_b"], col, 10.0, true)
	c.draw_line(p["el_b"], p["hand_b"], col, 9.0, true)
	c.draw_line(p["sh_f"], p["el_f"], col, 10.0, true)
	c.draw_line(p["el_f"], p["hand_f"], col, 9.0, true)
	c.draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)


# --------------------------------------------------------------- body parts

static func _limb(c: CanvasItem, a: Vector2, b: Vector2, col: Color, w: float) -> void:
	c.draw_line(a, b, OUTLINE, w + OUTLINE_W, true)
	c.draw_line(a, b, col, w, true)


static func _draw_arm(c: CanvasItem, p: Dictionary, pal: Dictionary, is_back: bool, t: float) -> void:
	var sleeve: Color = pal["sleeve_dark"] if is_back else pal["sleeve"]
	var skin: Color = pal["skin_dark"] if is_back else pal["skin"]
	var sh: Vector2 = p["sh_b"] if is_back else p["sh_f"]
	var el: Vector2 = p["el_b"] if is_back else p["el_f"]
	var hand: Vector2 = p["hand_b"] if is_back else p["hand_f"]
	_limb(c, sh, el, sleeve, 11.0)
	_limb(c, el, hand, sleeve, 9.5)
	# forearm guard
	var guard_a: Vector2 = el.lerp(hand, 0.45)
	var guard_b: Vector2 = el.lerp(hand, 0.95)
	_limb(c, guard_a, guard_b, pal["guard"] if not is_back else pal["guard_dark"], 12.0)
	if bool(p["fist_f"] if not is_back else p["fist_b"]):
		c.draw_circle(hand, 7.5, OUTLINE)
		c.draw_circle(hand, 5.8, skin)
	else:
		c.draw_circle(hand, 6.0, OUTLINE)
		c.draw_circle(hand, 4.6, skin)


static func _draw_leg(c: CanvasItem, p: Dictionary, pal: Dictionary, is_back: bool) -> void:
	var pant: Color = pal["pant_dark"] if is_back else pal["pant"]
	var shin: Color = pal["shin_dark"] if is_back else pal["shin"]
	var hip: Vector2 = p["hip"]
	var knee: Vector2 = p["knee_b"] if is_back else p["knee_f"]
	var foot: Vector2 = p["foot_b"] if is_back else p["foot_f"]
	_limb(c, hip, knee, pant, 15.0)
	_limb(c, knee, foot.lerp(knee, 0.22), shin, 12.0)
	# sandal
	var dir: Vector2 = (foot - knee).normalized()
	var side := Vector2(-dir.y, dir.x)
	c.draw_colored_polygon(
		PackedVector2Array([
			foot - side * 6.0 - dir * 3.0,
			foot + side * 6.0 - dir * 3.0,
			foot + side * 6.0 + dir * 8.0,
			foot - side * 6.0 + dir * 8.0,
		]),
		pal["sandal_dark"] if is_back else pal["sandal"]
	)
	c.draw_line(foot - side * 6.0 - dir * 3.0, foot + side * 6.0 - dir * 3.0, OUTLINE, 2.5, true)


static func _draw_torso(c: CanvasItem, p: Dictionary, pal: Dictionary) -> void:
	var hip: Vector2 = p["hip"]
	var chest: Vector2 = p["chest"]
	var axis: Vector2 = (chest - hip).normalized()
	var side := Vector2(-axis.y, axis.x)
	var half_bottom: float = 12.0
	var half_top: float = 15.0
	var body := PackedVector2Array([
		hip - side * half_bottom,
		chest - side * half_top,
		chest + side * half_top,
		hip + side * half_bottom,
	])
	_draw_poly(c, body, pal["suit"])
	# flak vest over the chest
	var v_bottom: Vector2 = hip.lerp(chest, 0.22)
	var v_top: Vector2 = chest + axis * 5.0
	var vest := PackedVector2Array([
		v_bottom - side * 12.5,
		v_top - side * 16.0,
		v_top + side * 16.0,
		v_bottom + side * 12.5,
	])
	_draw_poly(c, vest, pal["vest"])
	# cel shadow on the back half of the vest
	var shade := PackedVector2Array([
		v_bottom - side * 12.5,
		v_top - side * 16.0,
		chest - side * 3.0,
		hip - side * 3.0,
	])
	c.draw_colored_polygon(shade, Color(pal["vest_dark"].r, pal["vest_dark"].g, pal["vest_dark"].b, 0.85))
	# zipper + pockets + belt
	c.draw_line(v_bottom.lerp(v_top, 0.05), v_top, pal["vest_line"], 2.0, true)
	c.draw_rect(Rect2(v_bottom.x - 9.0, v_bottom.y - 18.0, 8.0, 9.0), pal["vest_line"])
	c.draw_rect(Rect2(v_bottom.x + 3.0, v_bottom.y - 18.0, 8.0, 9.0), pal["vest_line"])
	c.draw_rect(Rect2(hip.x - 13.0, hip.y - 4.0, 26.0, 7.0), pal["belt"])
	# mesh under-sleeve hint at the shoulders
	c.draw_circle(chest + side * 11.0 + axis * 6.0, 5.0, MESH)
	c.draw_circle(chest - side * 11.0 + axis * 6.0, 5.0, MESH)


static func _draw_scarf(c: CanvasItem, p: Dictionary, pal: Dictionary, t: float) -> void:
	var lift: float = float(p["scarf"])
	var wave: float = sin(t * 7.0) * (4.0 + lift * 6.0)
	var neck: Vector2 = p["chest"] + Vector2(0.0, -12.0)
	var tail := PackedVector2Array([
		neck + Vector2(-6.0, -4.0),
		neck + Vector2(-16.0, -2.0 + wave * 0.3),
		neck + Vector2(-40.0 - lift * 26.0, 6.0 + wave),
		neck + Vector2(-38.0 - lift * 22.0, 16.0 + wave * 0.6),
		neck + Vector2(-14.0, 8.0),
	])
	_draw_poly(c, tail, pal["accent_dark"])
	# collar wrap in front of the shoulders
	var collar := PackedVector2Array([
		neck + Vector2(-13.0, -6.0),
		neck + Vector2(12.0, -8.0),
		neck + Vector2(14.0, 6.0),
		neck + Vector2(-12.0, 8.0),
	])
	_draw_poly(c, collar, pal["accent"])


static func _draw_band_tail(c: CanvasItem, p: Dictionary, pal: Dictionary, t: float) -> void:
	var lift: float = float(p["band"])
	var wave: float = sin(t * 9.0) * 3.0
	var head: Vector2 = p["head"]
	var a: Vector2 = head + Vector2(-14.0, -4.0)
	var b: Vector2 = head + Vector2(-15.0, 4.0)
	var l: float = 22.0 + lift * 24.0
	var tail := PackedVector2Array([
		a,
		b,
		b + Vector2(-l, 3.0 + wave),
		a + Vector2(-l, 1.0 + wave * 0.8),
	])
	_draw_poly(c, tail, pal["band_cloth"])


static func _draw_head(c: CanvasItem, p: Dictionary, pal: Dictionary, t: float) -> void:
	var head: Vector2 = p["head"]
	var face: String = p["face"]
	# back hair
	_ellipse(c, head + Vector2(-2.0, 0.0), Vector2(18.0, 20.0), pal["hair_dark"], true)
	# face
	_ellipse(c, head, Vector2(16.0, 18.5), pal["skin"], true)
	# ear
	_ellipse(c, head + Vector2(-2.0, 3.0), Vector2(4.0, 6.0), pal["skin_dark"], false)
	# jaw shadow line
	c.draw_arc(head + Vector2(1.0, 2.0), 15.0, deg_to_rad(20.0), deg_to_rad(140.0), 10, Color(pal["skin_dark"].r, pal["skin_dark"].g, pal["skin_dark"].b, 0.55), 3.0, true)
	# headband band + metal plate with an original emblem
	var band := PackedVector2Array([
		head + Vector2(-17.0, -12.0),
		head + Vector2(16.0, -14.0),
		head + Vector2(16.0, -5.0),
		head + Vector2(-17.0, -4.0),
	])
	_draw_poly(c, band, pal["band_cloth"])
	var plate := PackedVector2Array([
		head + Vector2(-4.0, -14.0),
		head + Vector2(14.0, -15.0),
		head + Vector2(14.0, -4.0),
		head + Vector2(-4.0, -3.5),
	])
	_draw_poly(c, plate, Color("#cfd6dd"))
	c.draw_line(head + Vector2(5.0, -13.0), head + Vector2(5.0, -5.0), Color("#5d6672"), 1.6, true)
	c.draw_colored_polygon(
		PackedVector2Array([
			head + Vector2(5.0, -13.0),
			head + Vector2(11.0, -9.0),
			head + Vector2(5.0, -5.0),
			head + Vector2(-1.0, -9.0),
		]),
		Color("#2c333c")
	)
	# hair: a few ink-lined spikes, anime style
	var spikes := PackedVector2Array([
		head + Vector2(-16.0, -6.0),
		head + Vector2(-20.0, -18.0),
		head + Vector2(-8.0, -12.0),
		head + Vector2(-6.0, -24.0),
		head + Vector2(4.0, -14.0),
		head + Vector2(10.0, -26.0),
		head + Vector2(14.0, -12.0),
		head + Vector2(19.0, -20.0),
		head + Vector2(18.0, -6.0),
	])
	_draw_poly(c, spikes, pal["hair"])
	# front bangs over the band
	var bangs := PackedVector2Array([
		head + Vector2(-14.0, -8.0),
		head + Vector2(-6.0, -2.0),
		head + Vector2(0.0, -9.0),
		head + Vector2(7.0, -1.0),
		head + Vector2(14.0, -8.0),
		head + Vector2(15.0, -3.0),
		head + Vector2(-14.0, -3.0),
	])
	_draw_poly(c, bangs, pal["hair"])
	_draw_face(c, head, face, pal, t)


static func _draw_face(c: CanvasItem, head: Vector2, face: String, pal: Dictionary, t: float) -> void:
	var ink := Color("#1b1622")
	var eye_f: Vector2 = head + Vector2(11.0, 2.0)
	var eye_b: Vector2 = head + Vector2(2.0, 2.0)
	var blink: float = 0.0
	if face == "calm":
		blink = clampf(sin(t * 1.7) * 8.0, 0.0, 1.0)
	match face:
		"hurt", "ko":
			# squeezed-shut / knocked-out eyes
			for e in [eye_f, eye_b]:
				c.draw_line(e + Vector2(-4.0, -3.0), e + Vector2(4.0, 3.0), ink, 2.6, true)
				c.draw_line(e + Vector2(-4.0, 3.0), e + Vector2(4.0, -3.0), ink, 2.6, true)
			c.draw_circle(head + Vector2(8.0, 11.0), 3.4, ink)
		_:
			for e in [eye_b, eye_f]:
				var h: float = 4.6 * (1.0 - blink)
				_ellipse(c, e, Vector2(3.6, maxf(h, 0.6)), Color("#fdfdff"), false)
				if h > 1.6:
					_ellipse(c, e + Vector2(0.6, 0.4), Vector2(2.0, h * 0.85), ink, false)
			# brows: angled inward when straining
			if face == "strain":
				c.draw_line(head + Vector2(-2.0, -5.0), head + Vector2(6.0, -2.0), ink, 3.0, true)
				c.draw_line(head + Vector2(8.0, -2.0), head + Vector2(15.0, -6.0), ink, 3.0, true)
				c.draw_circle(head + Vector2(7.0, 12.0), 3.6, ink)
			else:
				c.draw_line(head + Vector2(-2.0, -6.0), head + Vector2(6.0, -7.0), ink, 2.4, true)
				c.draw_line(head + Vector2(8.0, -7.0), head + Vector2(15.0, -6.0), ink, 2.4, true)
				c.draw_line(head + Vector2(4.0, 10.0), head + Vector2(11.0, 9.5), ink, 2.2, true)
	# nose
	c.draw_line(head + Vector2(15.0, 5.0), head + Vector2(12.0, 7.0), Color(0.15, 0.12, 0.18, 0.8), 1.8, true)


static func _draw_aura(c: CanvasItem, p: Dictionary, pal: Dictionary, t: float, amount: float) -> void:
	var center: Vector2 = p["hip"].lerp(p["chest"], 0.45)
	var accent: Color = pal["accent"]
	for i in 5:
		var phase: float = t * 9.0 + float(i) * 1.7
		var h: float = 54.0 + sin(phase) * 16.0
		var w: float = 9.0 - float(i) * 0.6
		var x: float = -16.0 + float(i) * 8.0
		var flame := PackedVector2Array([
			center + Vector2(x - w, 20.0),
			center + Vector2(x - 10.0, -h),
			center + Vector2(x + w, 20.0),
		])
		c.draw_colored_polygon(flame, Color(accent.r, accent.g, accent.b, 0.16 * amount))
	c.draw_arc(center, 46.0, 0.0, TAU, 28, Color(accent.r, accent.g, accent.b, 0.28 * amount), 4.0, true)
	c.draw_arc(center, 34.0, 0.0, TAU, 24, Color(1.0, 1.0, 1.0, 0.14 * amount), 2.5, true)


static func _draw_chakra(c: CanvasItem, p: Dictionary, pal: Dictionary, t: float) -> void:
	var seal: float = float(p["seal"])
	if seal <= 0.01:
		return
	var mid: Vector2 = (p["hand_f"] + p["hand_b"]) * 0.5
	var pulse: float = 1.0 + sin(t * 30.0) * 0.12
	var r: float = (8.0 + seal * 4.0) * pulse
	c.draw_circle(mid, r * 1.7, Color(0.45, 0.78, 1.0, 0.22))
	c.draw_circle(mid, r, Color(0.7, 0.92, 1.0, 0.75))
	c.draw_circle(mid, r * 0.5, Color(1.0, 1.0, 1.0, 0.95))


# ------------------------------------------------------------------ helpers

static func _draw_poly(c: CanvasItem, pts: PackedVector2Array, col: Color) -> void:
	c.draw_colored_polygon(pts, col)
	var closed := PackedVector2Array(pts)
	closed.append(pts[0])
	c.draw_polyline(closed, OUTLINE, OUTLINE_W, true)


static func _ellipse(c: CanvasItem, center: Vector2, radii: Vector2, col: Color, outline: bool) -> void:
	var pts := PackedVector2Array()
	var steps := 22
	for i in steps:
		var a: float = TAU * float(i) / float(steps)
		pts.append(center + Vector2(cos(a) * radii.x, sin(a) * radii.y))
	if outline:
		_draw_poly(c, pts, col)
	else:
		c.draw_colored_polygon(pts, col)
