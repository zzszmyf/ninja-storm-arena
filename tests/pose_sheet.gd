extends SceneTree

# Dev tool: renders every character pose into one contact sheet so the artwork
# can be reviewed at a glance. Output: docs/pose_sheet.png

const POSES := ["idle", "run", "air", "attack", "kick", "proj", "block", "hurt", "ko"]


class Board:
	extends Node2D

	func _draw() -> void:
		draw_rect(Rect2(0.0, 0.0, 1600.0, 900.0), Color(0.09, 0.08, 0.14))
		var row := 0
		for slug in ["sora", "kaze"]:
			var base_y: float = 300.0 + row * 400.0
			draw_line(Vector2(0.0, base_y + 40.0), Vector2(1600.0, base_y + 40.0), Color(0.3, 0.3, 0.45), 2.0)
			var x: float = 40.0
			for pose in POSES:
				var info := Art.pose_info(slug, pose)
				var tex := Art.pose_texture(slug, pose)
				if tex == null or info.is_empty():
					x += 170.0
					continue
				var sc: float = float(info["s"]) * 1.15
				var w: float = float(info["w"]) * sc
				var h: float = float(info["h"]) * sc
				var ax: float = float(info["ax"]) * sc
				var ay: float = float(info["ay"]) * sc
				var slot: float = 170.0
				var anchor_x: float = x + slot * 0.5
				var y: float = base_y + 40.0 if pose != "ko" else base_y + 40.0
				draw_texture_rect(tex, Rect2(anchor_x - ax, y - ay, w, h), false, Color(1, 1, 1, 1))
				x += slot
			row += 1


func _initialize() -> void:
	DisplayServer.window_set_size(Vector2i(1600, 900))
	var board := Board.new()
	root.add_child(board)
	await process_frame
	await process_frame
	var img: Image = root.get_texture().get_image()
	img.save_png("/private/tmp/pose_sheet.png")
	print("pose sheet saved ", img.get_width(), "x", img.get_height())
	quit(0)
