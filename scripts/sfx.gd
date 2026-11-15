class_name Sfx
extends Node

# Central audio for the arena.
#
# The sounds themselves are rendered offline by tools/build_audio.py,
# tools/build_music.py and tools/gen_voices.py, then loaded from res://assets.
# This node owns the runtime side: a pool of players so overlapping hits never
# cut each other off, world positioning so a hit on the left comes out of the
# left speaker, pitch and level humanising so repeated jabs do not sound like a
# machine gun, ducking for the music, and graceful fallbacks.
#
# Everything is optional. If an audio file is missing the event falls back to a
# synthesised tone, and in headless mode (tests, CI) playback is recorded but
# silent, so the game always runs.

const SFX_DIR := "res://assets/audio/sfx/"
const VOICE_DIR := "res://assets/audio/voice/"
const MUSIC_DIR := "res://assets/audio/music/"

const POOL_SIZE := 20
const UI_POOL_SIZE := 6

# event -> file to load, a dB trim on top of the level baked in by the render
# tools, pitch variation, and whether the sound is placed in the world.
const EVENTS := {
	"hit_light": {"file": "hit_light", "gain": 0.0, "jitter": 0.13, "positional": true},
	"hit_medium": {"file": "hit_medium", "gain": 0.0, "jitter": 0.11, "positional": true},
	"hit_heavy": {"file": "hit_heavy", "gain": 0.0, "jitter": 0.08, "positional": true},
	"launcher": {"file": "launcher", "gain": 0.0, "jitter": 0.06, "positional": true},
	"whoosh_light": {"file": "whoosh_light", "gain": -3.0, "jitter": 0.15, "positional": true},
	"whoosh_heavy": {"file": "whoosh_heavy", "gain": -2.0, "jitter": 0.11, "positional": true},
	"block": {"file": "block", "gain": -1.0, "jitter": 0.10, "positional": true},
	"dash": {"file": "dash", "gain": -2.0, "jitter": 0.10, "positional": true},
	"poof": {"file": "poof", "gain": -4.0, "jitter": 0.16, "positional": true},
	"chakra_charge": {"file": "chakra_charge", "gain": -4.0, "jitter": 0.05, "positional": true},
	"chakra_shoot": {"file": "chakra_shoot", "gain": 0.0, "jitter": 0.07, "positional": true},
	"chakra_hit": {"file": "chakra_hit", "gain": 0.0, "jitter": 0.08, "positional": true},
	"jump": {"file": "jump", "gain": -3.0, "jitter": 0.14, "positional": true},
	"land": {"file": "land", "gain": -2.0, "jitter": 0.12, "positional": true},
	"ko": {"file": "ko", "gain": 0.0, "jitter": 0.0, "positional": true},
	"round_start": {"file": "round_start", "gain": 0.0, "jitter": 0.0, "positional": false},
	"time_up": {"file": "time_up", "gain": 0.0, "jitter": 0.0, "positional": false},
	"ui_move": {"file": "ui_move", "gain": 0.0, "jitter": 0.0, "positional": false},
	"ui_confirm": {"file": "ui_confirm", "gain": 0.0, "jitter": 0.0, "positional": false},
	"aura_loop": {"file": "aura_loop", "gain": -14.0, "jitter": 0.0, "positional": true},
}

# Voice barks, with the minimum gap between repeats of the same line.
const VOICE_LINES := {
	"attack_light": 0.34,
	"attack_heavy": 0.50,
	"technique": 0.60,
	"hurt": 0.40,
	"ko": 1.40,
	"win": 2.00,
}

# Event names used before the rendered palette existed, so older call sites
# keep working instead of silently losing their sound.
const LEGACY := {
	"hit": "hit_medium",
	"shoot": "chakra_shoot",
	"punch": "hit_light",
}

# The music bed is levelled on its own RMS, not on the 20 ms bursts the sound
# effects use, so this number is not comparable to the trims above. At -11 dB
# the loop measured ~22 dB under the effects in a busy exchange - audible on
# headphones and completely gone on a laptop speaker. -4 dB leaves it clearly
# present at roughly 14 dB under the hits, where duck() can still pull it away.
const MUSIC_VOLUME_DB := -4.0

var enabled := true
var log_events := false
## Tests flip this on to drive the real player pool under the dummy driver.
var force_playback := false
var master_db := -3.0

var _streams := {}
var _sfx_pool: Array[AudioStreamPlayer2D] = []
var _ui_pool: Array[AudioStreamPlayer] = []
var _sfx_cursor := 0
var _ui_cursor := 0
var _music: AudioStreamPlayer
var _music_track := ""
var _music_tween: Tween
var _aura: AudioStreamPlayer2D
var _voice_cooldown := {}
var _log: Array[String] = []
## Event names the game asked for that the palette does not define. The audio
## test fails on a non-empty list, which catches a typo'd call site.
var unknown_events: Array[String] = []
var _muted := false
var _paused := false
## Game clock, accumulated from `delta` rather than read from the wall. Voice
## cooldowns used to call Time.get_ticks_msec(), which made them depend on how
## fast the frame loop happened to be running: the same match barked a
## different number of times under `--fixed-fps` than in real time, and a
## paused game would let every cooldown expire. It also fed the shared RNG a
## different number of draws each run, which is what kept the audio test's
## coverage check flipping.
var _clock := 0.0


func _process(delta: float) -> void:
	if _paused:
		return
	_clock += delta


func _ready() -> void:
	_install_master_guard()
	for i in POOL_SIZE:
		var p := AudioStreamPlayer2D.new()
		# No distance falloff: the arena is one screen wide, and the point of
		# placing these in the world is stereo positioning, not walking away.
		p.attenuation = 0.0
		p.max_distance = 4096.0
		p.panning_strength = 0.7
		add_child(p)
		_sfx_pool.append(p)
	for i in UI_POOL_SIZE:
		var u := AudioStreamPlayer.new()
		add_child(u)
		_ui_pool.append(u)
	_music = AudioStreamPlayer.new()
	add_child(_music)
	_aura = AudioStreamPlayer2D.new()
	_aura.attenuation = 0.0
	_aura.max_distance = 4096.0
	_aura.panning_strength = 0.5
	add_child(_aura)


# ------------------------------------------------------------ output guard

# A finisher, the KO boom, the music bed and two voice barks can all be in
# flight at once, and the rendered assets are mastered hot enough (peaks around
# -0.5 dBFS) that their sum can leave full scale. Clipping is the harsh crackle
# that makes game audio sound cheap, so the master bus gets a limiter. Every
# per-sound level upstream still decides where the transients sit; this only
# catches the stack.
func _install_master_guard() -> void:
	var bus := AudioServer.get_bus_index("Master")
	if bus < 0 or output_guard_installed():
		return  # scene reloads reuse the same bus, so install it only once
	var effect: AudioEffect
	if ClassDB.class_exists("AudioEffectHardLimiter"):
		var hard := AudioEffectHardLimiter.new()
		hard.pre_gain_db = 0.0
		hard.ceiling_db = -0.8
		hard.release = 0.08
		effect = hard
	else:
		var soft := AudioEffectLimiter.new()
		soft.threshold_db = -1.5
		soft.ceiling_db = -0.8
		soft.soft_clip_db = 2.0
		soft.soft_clip_ratio = 0.6
		effect = soft
	AudioServer.add_bus_effect(bus, effect)


func output_guard_installed() -> bool:
	var bus := AudioServer.get_bus_index("Master")
	if bus < 0:
		return false
	for i in AudioServer.get_bus_effect_count(bus):
		var fx := AudioServer.get_bus_effect(bus, i)
		if fx is AudioEffectHardLimiter or fx is AudioEffectLimiter:
			return true
	return false


static func _is_headless() -> bool:
	return DisplayServer.get_name() == "headless"


func _silent() -> bool:
	return not enabled or (_is_headless() and not force_playback)


# ------------------------------------------------------------------- sfx

func play(name: String, volume_db := 0.0) -> void:
	play_at(name, Vector2.ZERO, volume_db, false)


func play_at(name: String, pos: Vector2, volume_db := 0.0, positional := true) -> void:
	var key: String = LEGACY.get(name, name)
	if not EVENTS.has(key):
		push_warning("Sfx: unknown event '%s'" % name)
		if not unknown_events.has(name):
			unknown_events.append(name)
		return
	var ev: Dictionary = EVENTS[key]
	if log_events:
		_log.append(key)
	if _silent():
		return
	var stream := _stream("sfx", String(ev["file"]))
	if stream == null:
		_play_fallback(key, pos, ev)
		return
	var pitch := 1.0
	var jitter: float = ev["jitter"]
	if jitter > 0.0:
		pitch = 1.0 + randf_range(-jitter, jitter)
	var gain: float = float(ev["gain"]) + volume_db + master_db
	if bool(ev["positional"]) and positional:
		_play_positional(stream, pos, gain, pitch)
	else:
		_play_ui(stream, gain, pitch)


func _play_positional(stream: AudioStream, pos: Vector2, gain_db: float, pitch: float) -> void:
	var p := _free_sfx_player()
	p.stream = stream
	p.position = pos
	p.volume_db = gain_db
	p.pitch_scale = pitch
	p.play()


func _play_ui(stream: AudioStream, gain_db: float, pitch: float) -> void:
	var p := _free_ui_player()
	p.stream = stream
	p.volume_db = gain_db
	p.pitch_scale = pitch
	p.play()


func _free_sfx_player() -> AudioStreamPlayer2D:
	for p in _sfx_pool:
		if not p.playing:
			return p
	# All busy: steal the oldest slot rather than dropping the sound.
	_sfx_cursor = (_sfx_cursor + 1) % _sfx_pool.size()
	return _sfx_pool[_sfx_cursor]


func _free_ui_player() -> AudioStreamPlayer:
	for p in _ui_pool:
		if not p.playing:
			return p
	_ui_cursor = (_ui_cursor + 1) % _ui_pool.size()
	return _ui_pool[_ui_cursor]


# ----------------------------------------------------------------- voice

func say(line: String, pos: Vector2, pitch := 1.0) -> void:
	if not VOICE_LINES.has(line):
		push_warning("Sfx: unknown voice line '%s'" % line)
		if not unknown_events.has(line):
			unknown_events.append(line)
		return
	var now := _clock
	var ready_at: float = _voice_cooldown.get(line, -1.0)
	if now < ready_at:
		return
	_voice_cooldown[line] = now + float(VOICE_LINES[line])
	if log_events:
		_log.append("voice:" + line)
	if _silent():
		return
	var stream := _stream("voice", line)
	if stream == null:
		return
	_play_positional(stream, pos, -3.0 + master_db, pitch * (1.0 + randf_range(-0.04, 0.04)))


# ----------------------------------------------------------------- music

func music(track: String, volume_db := MUSIC_VOLUME_DB, looping := true) -> void:
	if _music_track == track and _music != null and _music.playing:
		return
	_music_track = track
	if log_events:
		_log.append("music:" + track)
	if _silent():
		return
	# A pending fade-out must not keep driving the player we are about to reuse.
	if _music_tween != null and _music_tween.is_valid():
		_music_tween.kill()
	var stream := _stream("music", track)
	if stream == null:
		return
	if looping:
		_make_looping(stream)
	_music.stream = stream
	_music.volume_db = volume_db + master_db
	_music.play()


func stop_music(fade := 0.4) -> void:
	_music_track = ""
	if _silent() or _music == null:
		return
	if fade <= 0.0:
		_music.stop()
		return
	var from := _music.volume_db
	if _music_tween != null and _music_tween.is_valid():
		_music_tween.kill()
	_music_tween = create_tween()
	_music_tween.tween_method(func(v: float) -> void: _music.volume_db = v, from, -60.0, fade)
	_music_tween.tween_callback(_music.stop)


# Drop the music under a big moment, then bring it back.
func duck(amount_db := 6.0, seconds := 0.5) -> void:
	if _silent() or _music == null or not _music.playing:
		return
	var here := _music.volume_db
	var target := here - absf(amount_db)
	var tw := create_tween()
	tw.tween_property(_music, "volume_db", target, 0.08)
	tw.tween_interval(seconds)
	tw.tween_property(_music, "volume_db", here, 0.45)


# Pause keeps the current track position, so returning to the fight does not
# restart or fade the battle music. Gameplay never emits new sounds while the
# arena is paused, and the looping chakra hum follows the same switch.
func set_paused(on: bool) -> void:
	_paused = on
	if _music != null:
		_music.stream_paused = on
	if _aura != null:
		_aura.stream_paused = on


# -------------------------------------------------------------- aura loop

func aura(on: bool, pos := Vector2.ZERO) -> void:
	if _aura == null:
		return
	if on:
		_aura.position = pos
	if not on:
		if _aura.playing:
			_aura.stop()
		return
	if _aura.playing:
		return
	var stream := _stream("sfx", "aura_loop")
	if stream == null:
		return
	_make_looping(stream)
	var ev: Dictionary = EVENTS["aura_loop"]
	_aura.stream = stream
	_aura.volume_db = float(ev["gain"]) + master_db
	_aura.play()


func move_aura(pos: Vector2) -> void:
	if _aura != null and _aura.playing:
		_aura.position = pos


# ---------------------------------------------------------------- volume

func toggle_mute() -> bool:
	_muted = not _muted
	if not _is_headless():
		AudioServer.set_bus_mute(0, _muted)
	return _muted


func is_muted() -> bool:
	return _muted


# Release every player and cached stream. Called by the tests so the engine can
# shut down cleanly, and useful when a scene swap should drop all audio.
func shutdown() -> void:
	for node in get_children():
		if node is AudioStreamPlayer:
			(node as AudioStreamPlayer).stop()
			(node as AudioStreamPlayer).stream = null
		elif node is AudioStreamPlayer2D:
			(node as AudioStreamPlayer2D).stop()
			(node as AudioStreamPlayer2D).stream = null
	_streams.clear()
	unknown_events.clear()
	_music_track = ""


# -------------------------------------------------------------- fallbacks

# Minimal synth stand-in used only when a rendered asset is missing, so the
# game stays audible with an empty assets folder.
func _play_fallback(name: String, pos: Vector2, ev: Dictionary) -> void:
	var stream := _tone_for(name)
	if stream == null:
		return
	if bool(ev["positional"]):
		_play_positional(stream, pos, float(ev["gain"]) + master_db, 1.0)
	else:
		_play_ui(stream, float(ev["gain"]) + master_db, 1.0)


func _tone_for(name: String) -> AudioStreamWAV:
	match name:
		"hit_light", "hit_medium", "hit_heavy", "launcher":
			return _tone(220.0, 90.0, 0.07, "square", 0.5)
		"block":
			return _tone(150.0, 60.0, 0.09, "square", 0.5)
		"chakra_shoot", "chakra_hit":
			return _tone(520.0, 210.0, 0.13, "saw", 0.4)
		"ko":
			return _tone(500.0, 55.0, 0.65, "saw", 0.7)
		_:
			return _tone(300.0, 200.0, 0.05, "square", 0.3)


func _tone(f0: float, f1: float, dur: float, shape: String, vol: float) -> AudioStreamWAV:
	var rate := 22050
	var n := int(dur * float(rate))
	var data := PackedByteArray()
	data.resize(n * 2)
	var rng := RandomNumberGenerator.new()
	rng.seed = hash(f0) + hash(f1)
	var phase := 0.0
	for i in n:
		var t := float(i) / float(rate)
		var f := lerpf(f0, f1, t / dur)
		phase += f / float(rate)
		var w: float = phase - floor(phase)
		var s := 0.0
		match shape:
			"square":
				s = 1.0 if w < 0.5 else -1.0
			"saw":
				s = w * 2.0 - 1.0
			"noise":
				s = rng.randf_range(-1.0, 1.0)
			_:
				s = sin(TAU * w)
		var env := minf(1.0, t * 60.0) * maxf(0.0, 1.0 - t / dur)
		var v := clampf(s * env * vol, -1.0, 1.0)
		data.encode_s16(i * 2, int(v * 32767.0))
	var wav := AudioStreamWAV.new()
	wav.format = AudioStreamWAV.FORMAT_16_BITS
	wav.mix_rate = rate
	wav.stereo = false
	wav.data = data
	return wav


# ---------------------------------------------------------------- loading

func _stream(kind: String, name: String) -> AudioStream:
	var key := kind + ":" + name
	if _streams.has(key):
		return _streams[key]
	var dir := SFX_DIR
	if kind == "voice":
		dir = VOICE_DIR
	elif kind == "music":
		dir = MUSIC_DIR
	var path := dir + name + ".wav"
	var stream: AudioStream = null
	if ResourceLoader.exists(path):
		stream = load(path) as AudioStream
	_streams[key] = stream
	return stream


func _make_looping(stream: AudioStream) -> void:
	var wav := stream as AudioStreamWAV
	if wav == null or wav.loop_mode == AudioStreamWAV.LOOP_FORWARD:
		return
	var bytes_per_frame := 2
	match wav.format:
		AudioStreamWAV.FORMAT_8_BITS:
			bytes_per_frame = 1
		AudioStreamWAV.FORMAT_16_BITS:
			bytes_per_frame = 2
		_:
			return  # compressed formats carry their own loop metadata
	if wav.stereo:
		bytes_per_frame *= 2
	wav.loop_mode = AudioStreamWAV.LOOP_FORWARD
	wav.loop_begin = 0
	wav.loop_end = wav.data.size() / bytes_per_frame


# ------------------------------------------------------ reporting / tests

func event_names() -> Array:
	return EVENTS.keys()


func voice_lines() -> Array:
	return VOICE_LINES.keys()


func recorded() -> Array[String]:
	return _log


func clear_log() -> void:
	_log.clear()


# Every asset the runtime expects, for the audio verification test.
func expected_assets() -> Array[String]:
	var out: Array[String] = []
	for name in EVENTS:
		out.append(SFX_DIR + String(EVENTS[name]["file"]) + ".wav")
	for line in VOICE_LINES:
		out.append(VOICE_DIR + line + ".wav")
	out.append(MUSIC_DIR + "battle_loop.wav")
	out.append(MUSIC_DIR + "result_sting.wav")
	return out


func missing_assets() -> Array[String]:
	var out: Array[String] = []
	for path in expected_assets():
		if not ResourceLoader.exists(path):
			out.append(path)
	return out


func active_players() -> int:
	var n := 0
	if _music != null and _music.playing:
		n += 1
	if _aura != null and _aura.playing:
		n += 1
	for p in _sfx_pool:
		if p.playing:
			n += 1
	for p in _ui_pool:
		if p.playing:
			n += 1
	return n


func music_node() -> AudioStreamPlayer:
	return _music


func aura_node() -> AudioStreamPlayer2D:
	return _aura
