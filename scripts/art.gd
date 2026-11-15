class_name Art
extends RefCounted

# Loads the generated anime artwork that lives under res://assets.
#
# Everything is optional: when a manifest entry or PNG is missing the fighter
# falls back to the code-drawn cel-shaded rig in ninja_look.gd, so the game
# always runs even with an empty assets folder.

const MANIFEST_PATH := "res://assets/characters/manifest.json"
const STAGE_PATH := "res://assets/stage/dusk_village.png"

static var _characters: Dictionary = {}
static var _textures: Dictionary = {}
static var _manifest_loaded := false
static var _stage: Texture2D = null
static var _stage_loaded := false


static func _load_manifest() -> void:
	if _manifest_loaded:
		return
	_manifest_loaded = true
	if not FileAccess.file_exists(MANIFEST_PATH):
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST_PATH))
	if parsed is Dictionary:
		_characters = parsed


static func has_character(slug: String) -> bool:
	_load_manifest()
	return _characters.has(slug)


static func pose_info(slug: String, pose: String) -> Dictionary:
	_load_manifest()
	if not _characters.has(slug):
		return {}
	var entry: Dictionary = _characters[slug]
	var poses: Dictionary = entry.get("poses", {})
	if not poses.has(pose):
		return {}
	return poses[pose]


static func _texture_for(rel_path: String) -> Texture2D:
	if rel_path.is_empty():
		return null
	if _textures.has(rel_path):
		return _textures[rel_path]
	var path := "res://assets/characters/" + rel_path
	var tex: Texture2D = null
	if ResourceLoader.exists(path):
		tex = load(path) as Texture2D
	_textures[rel_path] = tex
	return tex


static func pose_texture(slug: String, pose: String) -> Texture2D:
	var info := pose_info(slug, pose)
	if info.is_empty():
		return null
	return _texture_for(String(info.get("file", "")))


static func flash_texture(slug: String, pose: String) -> Texture2D:
	var info := pose_info(slug, pose)
	if info.is_empty():
		return null
	return _texture_for(String(info.get("flash", "")))


static func portrait_texture(slug: String) -> Texture2D:
	_load_manifest()
	if not _characters.has(slug):
		return null
	var entry: Dictionary = _characters[slug]
	return _texture_for(String(entry.get("portrait", "")))


static func display_name(slug: String) -> String:
	_load_manifest()
	if not _characters.has(slug):
		return slug.to_upper()
	var entry: Dictionary = _characters[slug]
	return String(entry.get("display", slug.to_upper()))


static func stage_texture() -> Texture2D:
	if _stage_loaded:
		return _stage
	_stage_loaded = true
	if ResourceLoader.exists(STAGE_PATH):
		_stage = load(STAGE_PATH) as Texture2D
	return _stage
