extends SceneTree

# Dev tool: verifies every generated asset the game expects is present and
# loadable, then exits non-zero if anything is missing.

const POSES := ["idle", "run", "air", "attack", "kick", "proj", "block", "hurt", "ko"]


func _initialize() -> void:
	var missing := 0
	for slug in ["sora", "kaze"]:
		if not Art.has_character(slug):
			print("MISSING character entry: ", slug)
			missing += 1
			continue
		for pose in POSES:
			var info := Art.pose_info(slug, pose)
			var tex := Art.pose_texture(slug, pose)
			var flash := Art.flash_texture(slug, pose)
			var ok := not info.is_empty() and tex != null and flash != null
			if not ok:
				missing += 1
			print(
				"%s %-7s %s  tex=%s %s  flash=%s" % [
					slug, pose, "OK " if ok else "FAIL",
					"null" if tex == null else str(tex.get_width()) + "x" + str(tex.get_height()),
					"anchor_x=%.0f" % float(info.get("ax", 0.0)) if not info.is_empty() else "",
					"null" if flash == null else "ok",
				]
			)
		var portrait := Art.portrait_texture(slug)
		if portrait == null:
			missing += 1
		print("  portrait: ", "null" if portrait == null else str(portrait.get_width()))
	var stage := Art.stage_texture()
	if stage == null:
		missing += 1
	print("stage: ", "null" if stage == null else str(stage.get_width()), "x", "0" if stage == null else str(stage.get_height()))
	print("VERIFY ", "OK" if missing == 0 else "MISSING=%d" % missing)
	quit(0 if missing == 0 else 1)
