"""Turn raw model output into game-ready sprites.

Raw generations are big (1024x1536), have an uneven transparent edge, sometimes
carry a few stray specks, and — crucially — each pose is drawn at a slightly
different scale because the model reframes to fit the action into the canvas.
This module fixes all of that so every pose of a character ends up at the same
on-screen size, anchored at the feet, which is what the game needs.
"""

from __future__ import annotations

from collections import deque

import numpy as np
from PIL import Image, ImageFilter

# Alpha below this counts as "not the character" when measuring the silhouette.
ALPHA_THRESHOLD = 24
# Fraction of the silhouette to keep: everything under it is treated as a speck.
KEEP_FRACTION = 0.015
# Transparent breathing room added around the trimmed sprite (in output pixels).
PAD = 3


def load_rgba(path) -> Image.Image:
    img = Image.open(path)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    return img


def normalize_alpha(img: Image.Image) -> Image.Image:
    """Rescale the alpha channel to use the full 0-255 range and trim haze."""
    arr = np.array(img, dtype=np.uint8)
    alpha = arr[:, :, 3].astype(np.int16)
    top = int(alpha.max())
    if top <= 1:
        return img
    # Faint values below `low` become fully transparent, `top` becomes 255.
    low = max(6, min(40, top // 12))
    scaled = (alpha - low) * 255.0 / max(1, top - low)
    arr[:, :, 3] = np.clip(scaled, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _label_keep_mask(mask: np.ndarray) -> np.ndarray:
    """Flood-fill the silhouette at 1/4 resolution and return the keep mask.

    Keeps the biggest connected blob plus any blob at least KEEP_FRACTION of
    its size (which preserves attached gear but drops stray specks), then
    scales the result back up.
    """
    h, w = mask.shape
    small = np.array(
        Image.fromarray((mask * 255).astype(np.uint8)).resize(
            (max(1, w // 4), max(1, h // 4)), Image.BILINEAR
        )
    ) > 110
    sh, sw = small.shape
    labels = np.zeros((sh, sw), dtype=np.int32)
    sizes = [0]
    current = 0
    for sy in range(sh):
        for sx in range(sw):
            if not small[sy, sx] or labels[sy, sx]:
                continue
            current += 1
            count = 0
            queue = deque([(sy, sx)])
            labels[sy, sx] = current
            while queue:
                y, x = queue.popleft()
                count += 1
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < sh and 0 <= nx < sw and small[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = current
                        queue.append((ny, nx))
            sizes.append(count)
    if current <= 1:
        return mask
    biggest = max(range(1, current + 1), key=lambda i: sizes[i])
    keep_ids = [i for i in range(1, current + 1) if sizes[i] >= sizes[biggest] * KEEP_FRACTION]
    keep_small = np.isin(labels, keep_ids)
    keep = np.array(
        Image.fromarray((keep_small * 255).astype(np.uint8)).resize(
            (w, h), Image.BILINEAR
        )
    ) > 110
    return mask & keep


def clean(img: Image.Image) -> Image.Image:
    """Normalise alpha, drop stray islands and soften the jagged edge a touch."""
    img = normalize_alpha(img)
    arr = np.array(img, dtype=np.uint8)
    mask = arr[:, :, 3] > ALPHA_THRESHOLD
    if mask.any():
        mask = _label_keep_mask(mask)
        arr[:, :, 3] = np.where(mask, arr[:, :, 3], 0).astype(np.uint8)
    out = Image.fromarray(arr, "RGBA")
    # Rebuild the alpha edge from a slightly blurred mask so the cut looks like
    # an anti-aliased cel rather than a hard pixel staircase.
    alpha = out.getchannel("A").filter(ImageFilter.GaussianBlur(0.6))
    out.putalpha(alpha)
    return out


def stats(img: Image.Image) -> dict:
    """Silhouette measurements used for scale normalisation and anchoring."""
    arr = np.array(img, dtype=np.uint8)
    alpha = arr[:, :, 3]
    mask = alpha > ALPHA_THRESHOLD
    if not mask.any():
        raise ValueError("image has an empty silhouette")
    ys, xs = np.nonzero(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    height = y1 - y0

    # Horizontal anchor: median x of the silhouette in the hip band. The median
    # ignores an extended kicking leg and lands on the body's own column.
    band_top = y0 + int(height * 0.40)
    band_bottom = y0 + max(int(height * 0.62), int(height * 0.40) + 1)
    band = mask[band_top:band_bottom, :]
    band_xs = np.nonzero(band)[1] if band.any() else xs
    anchor_x = float(np.median(band_xs))
    return {
        "bbox": (x0, y0, x1, y1),
        "height": height,
        "width": x1 - x0,
        "area": int(mask.sum()),
        "anchor_x": anchor_x,
        "weight": float(alpha[mask].mean()) / 255.0,
    }


def scaled_copy(img: Image.Image, factor: float) -> Image.Image:
    w = max(1, int(round(img.width * factor)))
    h = max(1, int(round(img.height * factor)))
    return img.resize((w, h), Image.LANCZOS)


def trim(img: Image.Image, anchor_x: float, bbox) -> tuple:
    """Crop to the silhouette (plus padding) and return (image, ax, ay)."""
    x0, y0, x1, y1 = bbox
    left = max(0, x0 - PAD)
    top = max(0, y0 - PAD)
    right = min(img.width, x1 + PAD)
    bottom = min(img.height, y1 + PAD)
    cropped = img.crop((left, top, right, bottom))
    return cropped, anchor_x - left, y1 - top


def flash_from(img: Image.Image) -> Image.Image:
    """A flat white silhouette used for the hit-flash overlay."""
    arr = np.array(img, dtype=np.uint8)
    alpha = arr[:, :, 3]
    white = np.zeros_like(arr)
    white[:, :, 0:3] = 255
    white[:, :, 3] = alpha
    return Image.fromarray(white, "RGBA")


def scale_factor(ref: dict, pose: dict, mode: str) -> float:
    """How much to resize `pose` so it matches the reference pose's size."""
    if mode == "area":
        # A limb keeps roughly the same projected area whether it is bent or
        # extended, so total silhouette area is a decent scale probe for poses
        # whose bounding box changes shape (airborne, lying down).
        raw = (ref["area"] / max(1, pose["area"])) ** 0.5
    else:
        raw = ref["height"] / max(1, pose["height"])
    # Damped: never trust the estimate so far that a pose ends up wildly off.
    return min(max(raw, 0.60), 1.65)
