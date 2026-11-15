"""Art direction for the game.

This file is the single source of truth for *how the game looks*: the shared
style block that every image inherits, the two fighters' designs and the
per-pose prompts. Tweak here, re-run ``tools/build_art.py``, and the whole art
set is regenerated consistently.

The target look is the cel-shaded Japanese TV anime of the early-2000s shonen
ninja era: thick ink outlines, flat two-tone shading, saturated colours, spiky
hair clumps and a single bright catchlight in each eye.
"""

from __future__ import annotations

STYLE = (
    "Japanese 2D TV anime cel-shaded illustration, in the exact visual style of a "
    "late-1990s / early-2000s weekly shonen NINJA anime: thick confident black ink "
    "outlines of even weight, flat two-tone cel shading, hard-edged cast shadows, "
    "saturated punchy colours, sharp white specular highlights on hair and metal, "
    "spiky layered hair clumps, large expressive eyes with a single bright catchlight, "
    "clean animation-quality lineart, flat colour fills with no airbrush gradients. "
    "Professional anime key-visual / animation cel quality. "
)

FORBID = (
    "Strictly: no text, no letters, no watermark, no signature, no logo, no frame, "
    "no border, no speech bubble, no collage, no multiple views, no turnaround sheet, "
    "no grid, only ONE single character, correct anime anatomy, exactly two arms and "
    "two legs with five fingers per hand, no photorealistic rendering, no 3D render, "
    "no western cartoon style, no oil painting, no sketchy rough lines, no blurry "
    "soft shading."
)

FIGHT_VIEW = (
    "The whole figure is drawn in a three-quarter SIDE view facing to the RIGHT of "
    "the image, head to toe fully visible and nothing cropped, the body centred with "
    "generous empty margin on every side. The character is isolated on a fully "
    "transparent background with absolutely no scenery, no horizon, no ground plane, "
    "no shadow on the floor and no glow behind the body. "
)

CHARACTERS = {
    "sora": {
        "display": "SORA",
        "design": (
            "An original 13-year-old ninja boy, the hot-blooded hero type. "
            "Bright golden-blond spiky hair in sharp upward clumps, two long strands "
            "framing the face, big round sky-blue eyes, three faint whisker-like marks "
            "on each cheek, small confident grin. He wears a bright orange zip-up "
            "jacket with black shoulders and a high black collar, over a dark navy "
            "short-sleeve shirt; dark navy shin-length trousers cropped at the calf; "
            "blue open-toed ninja sandals; a blue cloth forehead protector with a "
            "polished metal plate bearing a spiral leaf engraving, tied with two long "
            "blue tails hanging at the back of the head; white bandage wraps on both "
            "forearms and knuckles; a black kunai pouch strapped to the right thigh "
            "with two silver kunai handles poking out; a small dark green scroll case "
            "clipped at the left hip. Colour scheme: orange, black, navy blue and gold, "
            "with warm bronze skin."
        ),
        "palette": "orange #F2792B, black #1B1A22, navy #23335E, blond #F6D046, metal #C9D3DE",
    },
    "kaze": {
        "display": "KAZE",
        "design": (
            "An original 14-year-old ninja boy, the cool elite rival. Porcelain pale "
            "skin, straight jet-black hair in layered spikes falling over the forehead, "
            "sharp narrow dark grey eyes with a calm unreadable stare, no smile. "
            "He wears a high-collared dark indigo sleeveless training shirt, a white "
            "cloth sash belt at the waist, black slim ninja trousers with white knee "
            "guards and white shin bindings, blue open-toed ninja sandals, a blue "
            "cloth forehead protector with a polished metal plate bearing a spiral "
            "leaf engraving sitting straight across his brow, and a long straight "
            "katana in a black lacquered scabbard strapped diagonally across his back. "
            "White bandage wraps on his forearms and a single blue cord wrapped around "
            "the right upper arm. Colour scheme: indigo, black, white and one blue "
            "accent, cold and sharp."
        ),
        "palette": "indigo #2B2F55, black #16161C, white #F2F4F8, blue #3E6FD0, pale skin #F6E3D8",
    },
}

# --------------------------------------------------------------------- poses
# ``scale`` tells the post-processor how to work out the sprite's scale:
#   "height" - bbox height is a good proxy for the character's size (grounded)
#   "area"   - limbs extend sideways / the silhouette changes (airborne, KO)
POSES = [
    {
        "key": "idle",
        "scale": "height",
        "size": "1024x1536",
        "reference": True,
        "prompt": (
            "Full-body idle battle stance: knees slightly bent, feet planted wide, "
            "weight settled on the back foot, both fists loose and ready at hip height, "
            "shoulders relaxed, calm confident determined face looking forward, hair "
            "and forehead-protector tails resting still."
        ),
    },
    {
        "key": "run",
        "scale": "height",
        "size": "1024x1536",
        "prompt": (
            "Full-body sprinting toward the right at full speed: deep forward lean of "
            "the torso, the front leg driving forward with the knee up and the back leg "
            "fully extended behind pushing off the ground, arms pumping front and back, "
            "fists clenched, hair and clothing streaming straight backwards, narrowed "
            "focused eyes, slight motion streaks behind the heels."
        ),
    },
    {
        "key": "air",
        "scale": "area",
        "size": "1024x1536",
        "prompt": (
            "Full-body airborne ninja leap toward the right: both knees tucked up "
            "tightly under the chest, one arm swung forward and the other pulled back "
            "for balance, toes pointed, jacket hem and forehead-protector tails "
            "fluttering upwards, hair blown upward, determined expression. The figure "
            "floats in mid-air, compact and curled."
        ),
    },
    {
        "key": "attack",
        "scale": "height",
        "size": "1024x1536",
        "prompt": (
            "Full-body attack pose throwing a powerful straight right punch toward the "
            "right: hips and shoulders twisted hard into the punch, the right arm fully "
            "extended horizontally at chest height with a clenched fist, the left fist "
            "pulled back tight to the hip, back leg extended and front knee bent, fierce "
            "shouting expression with gritted teeth, short speed lines behind the fist."
        ),
    },
    {
        "key": "kick",
        "scale": "height",
        "size": "1024x1536",
        "prompt": (
            "Full-body finisher pose: a high roundhouse kick to the right, the right "
            "leg fully extended horizontally at head height with the foot flexed, the "
            "standing left leg straight and supporting, torso leaning back and away "
            "from the kick, both arms swinging outward for balance, ferocious focused "
            "expression, short radial speed lines around the kicking foot."
        ),
    },
    {
        "key": "proj",
        "scale": "height",
        "size": "1024x1536",
        "prompt": (
            "Full-body ninjutsu technique pose: both palms thrust forward toward the "
            "right at chest height, a small swirling pale-blue chakra energy sphere "
            "held between the hands with a few white sparks and a thin swirling wind "
            "ring around it, elbows slightly bent, feet staggered in a braced stance, "
            "torso leaning forward into the technique, clothing and hair blown backwards "
            "by the wind, intense concentrated expression."
        ),
    },
    {
        "key": "block",
        "scale": "height",
        "size": "1024x1536",
        "prompt": (
            "Full-body defensive guard pose: both forearms crossed in an X in front of "
            "the face and chest, fists closed, shoulders raised, body turned slightly "
            "away from the incoming attack, knees bent and braced wide, leaning back a "
            "little, eyes narrowed and focused over the crossed arms."
        ),
    },
    {
        "key": "hurt",
        "scale": "height",
        "size": "1024x1536",
        "prompt": (
            "Full-body hit-reaction pose: struck hard and thrown backwards, torso and "
            "head snapped back away from the attacker, both arms flung outward and up, "
            "the front leg lifted off the ground and trailing, body arched, eyes "
            "squeezed shut and mouth open in pain, sweat drops and impact lines in "
            "front of the chest."
        ),
    },
    {
        "key": "ko",
        "scale": "area",
        "size": "1536x1024",
        "prompt": (
            "Full-body knocked-out pose: the character lies flat on their BACK on the "
            "ground, seen from a low angle at the side, arms spread out loosely on the "
            "floor, legs apart and slack, head turned to the right resting on the "
            "ground, eyes closed with a small dizzy swirl, mouth open in a faint, hair "
            "spread out on the floor, clothing rumpled. Completely horizontal body."
        ),
    },
]

PORTRAIT_PROMPT = (
    "Square head-and-shoulders anime character portrait of the same character, "
    "facing the viewer with a slight three-quarter turn, shoulders and chest visible, "
    "hair and forehead protector fully readable, dramatic dusk rim light from the "
    "right, a simple dark indigo-to-black diagonal gradient background with a few "
    "floating embers, cel-shaded, bold ink outlines, determined expression."
)

STAGE_PROMPT = (
    "Japanese 2D anime background painting, cel-shaded, of a hidden ninja village at "
    "golden-hour dusk. Wide 16:9 establishing shot. In the upper half: a warm orange "
    "and magenta sunset sky with layered clouds and a low sun, distant forested "
    "mountains, and a tall carved cliff on the left whose rock face bears a row of "
    "four giant stylised stone faces of legendary village leaders. In the middle: a "
    "cluster of traditional wooden buildings with dark tiled roofs, paper lanterns, "
    "narrow streets, water towers and television antennas, a few hanging banners. In "
    "the lower third: a broad empty packed-dirt training plaza with a low stone wall, "
    "empty of people, lit by warm sunset light with long purple shadows. No "
    "characters, no people, no text, no watermark, no UI. Painted like a late-1990s "
    "anime background art cel: hard-edged shadows, saturated warm colours, clean ink "
    "outlines on the architecture."
)

# ------------------------------------------------------------------ effects
# Anime effect art, always drawn on a transparent background so the renderer
# can put them on top of the fight with additive blending.
FX = {
    "chakra_orb": {
        "size": "1024x1024",
        "prompt": (
            "Japanese 2D anime special-attack effect art: one single swirling sphere "
            "of pale-blue chakra energy. A perfectly round glowing orb with a blinding "
            "white core, several translucent ribbons of blue chakra spiralling tightly "
            "around the sphere, a thin ring of white wind swirling around its equator, "
            "a few tiny white sparks flying off. Cel-shaded with hard-edged highlights "
            "and a bold dark blue ink outline, saturated cyan-blue and white palette, "
            "clean animation-cel effect art. The orb is centred and isolated on a fully "
            "transparent background, filling most of the frame, no character, no hands, "
            "no scenery, no text, no watermark, no frame, no border, not a photo, not 3D."
        ),
    },
    "hit_spark": {
        "size": "1024x1024",
        "prompt": (
            "Japanese 2D anime impact effect art: a sharp four-point starburst flash of "
            "pure white and pale-yellow light with a bright white core, a thin circular "
            "shockwave ring around it and short radial speed lines shooting outward. "
            "Flat cel-shaded anime effect art with hard-edged shapes and a bold dark ink "
            "outline, high contrast, glowing white centre. Centred and isolated on a "
            "fully transparent background, filling most of the frame, no character, no "
            "scenery, no text, no watermark, no frame, no border, not a photo, not 3D."
        ),
    },
    "chakra_aura": {
        "size": "1024x1536",
        "prompt": (
            "Japanese 2D anime chakra aura effect art: a tall vertical column of "
            "translucent blue-white energy with wispy flame-like tongues of chakra "
            "licking upward, a soft cyan inner glow and a thin bright outer edge, a few "
            "faint embers drifting up. Cel-shaded anime effect art with hard-edged "
            "shapes, cyan and white palette. Centred, taller than it is wide, isolated on "
            "a fully transparent background, no character, no body, no scenery, no text, "
            "no watermark, no frame, no border, not a photo, not 3D."
        ),
    },
}
