from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def safe_name(raw: str) -> str:
    keep = "._-"
    return "".join(ch for ch in raw if ch.isalnum() or ch in keep) or "image.png"


def decode_data_url(data_url: str) -> bytes:
    header, payload = data_url.split(",", 1)
    if "base64" not in header:
        return payload.encode("utf-8")
    return base64.b64decode(payload)


def hex_to_bgr(hex_color: str) -> np.ndarray:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = ''.join([c * 2 for c in hex_color])
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return np.array([b, g, r], dtype=np.uint8)


def bgr_to_hex(bgr: np.ndarray) -> str:
    b, g, r = int(bgr[0]), int(bgr[1]), int(bgr[2])
    return f"#{r:02x}{g:02x}{b:02x}"


def parse_image_request(req: Any, upload_dir: Path) -> tuple[np.ndarray, dict[str, Any]]:
    # Supports multipart form upload, base64 data URL, or image URL from this backend.
    file_obj = req.files.get("image") or req.files.get("room")
    if file_obj:
        raw = file_obj.read()
        image = Image.open(BytesIO(raw)).convert("RGB")
        arr = np.array(image)
        filename = f"{utc_stamp()}_{safe_name(file_obj.filename or 'upload.png')}"
        image.save(upload_dir / filename)
        return arr, {
            "source": "multipart",
            "filename": filename,
            "url": f"/uploads/{filename}",
        }

    body = req.get_json(silent=True) or {}
    image_data = body.get("imageData") or body.get("image_data")
    if isinstance(image_data, str) and image_data.startswith("data:image"):
        raw = decode_data_url(image_data)
        image = Image.open(BytesIO(raw)).convert("RGB")
        arr = np.array(image)
        digest = hashlib.sha1(raw).hexdigest()[:10]
        filename = f"{utc_stamp()}_{digest}.png"
        image.save(upload_dir / filename)
        return arr, {
            "source": "data_url",
            "filename": filename,
            "url": f"/uploads/{filename}",
        }

    image_url = body.get("imageUrl") or body.get("image_url")
    if isinstance(image_url, str):
        if image_url.startswith("data:image"):
            raw = decode_data_url(image_url)
            image = Image.open(BytesIO(raw)).convert("RGB")
            arr = np.array(image)
            digest = hashlib.sha1(raw).hexdigest()[:10]
            filename = f"{utc_stamp()}_{digest}.png"
            image.save(upload_dir / filename)
            return arr, {
                "source": "data_url",
                "filename": filename,
                "url": f"/uploads/{filename}",
            }

        from urllib.parse import urlparse

        parsed = urlparse(image_url)
        local_path = parsed.path
        if local_path.startswith("/api/uploads/"):
            local_path = local_path.replace("/api/uploads/", "/uploads/", 1)

        if local_path.startswith("/uploads/"):
            filename = local_path.replace("/uploads/", "", 1)
            path = upload_dir / filename
            if not path.exists():
                raise ValueError("Referenced upload does not exist")
            image = Image.open(path).convert("RGB")
            return np.array(image), {
                "source": "uploaded_url",
                "filename": filename,
                "url": parsed.path,
            }

    raise ValueError("Provide an image as multipart field 'image', JSON 'imageData', or JSON 'imageUrl'")


def resize_max(image: np.ndarray, max_side: int = 650) -> np.ndarray:
    h, w = image.shape[:2]
    if max(h, w) <= max_side:
        return image
    scale = max_side / max(h, w)
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def bbox_from_mask(mask: np.ndarray) -> list[int]:
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return [0, 0, 0, 0]
    x1, x2 = int(xs.min()), int(xs.max())
    y1, y2 = int(ys.min()), int(ys.max())
    return [x1, y1, x2 - x1, y2 - y1]


def mask_to_png_data_url(mask: np.ndarray, index: int = 0) -> str:
    if cv2 is None:
        raise RuntimeError('OpenCV is required to build mask overlays')
    h, w = mask.shape
    colors = [
        (0, 255, 255, 120),
        (255, 0, 255, 120),
        (255, 255, 0, 120),
        (0, 180, 255, 120),
        (255, 180, 0, 120),
        (120, 255, 120, 120),
        (255, 80, 80, 120),
        (80, 255, 180, 120),
    ]
    color = colors[index % len(colors)]
    overlay = np.zeros((h, w, 4), dtype=np.uint8)
    overlay[mask.astype(bool)] = color
    success, buffer = cv2.imencode('.png', overlay)
    if not success:
        return ''
    return 'data:image/png;base64,' + base64.b64encode(buffer).decode('utf-8')


def recolor_area(image: np.ndarray, mask: np.ndarray, hex_color: str, alpha: float = 0.55) -> np.ndarray:
    result = image.copy()
    color = hex_to_bgr(hex_color)
    color_layer = image.copy()
    color_layer[mask] = color
    blended = cv2.addWeighted(color_layer, alpha, image, 1 - alpha, 0)
    result[mask] = blended[mask]
    return result


def apply_furniture_style(image: np.ndarray, mask: np.ndarray, style_name: str) -> np.ndarray:
    style_name = style_name.lower().strip()
    h, w = image.shape[:2]
    texture = np.zeros_like(image)
    if style_name == 'wood':
        texture[:] = hex_to_bgr('#9B6A3C')
        for y in range(0, h, 12):
            cv2.line(texture, (0, y), (w, y), hex_to_bgr('#5C3A21').tolist(), 2)
    elif style_name == 'modern':
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray_3 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        base = np.full_like(image, hex_to_bgr('#D8DEE9'))
        texture = cv2.addWeighted(gray_3, 0.6, base, 0.4, 0)
    elif style_name == 'minimal':
        texture[:] = hex_to_bgr('#E8E2D6')
    elif style_name == 'velvet':
        texture[:] = hex_to_bgr('#5B2C6F')
        noise = np.random.randint(0, 35, image.shape, dtype=np.uint8)
        texture = cv2.add(texture, noise)
        texture = cv2.GaussianBlur(texture, (9, 9), 0)
    else:
        texture[:] = hex_to_bgr('#C0C0C0')
    result = image.copy()
    styled = cv2.addWeighted(image, 0.25, texture, 0.75, 0)
    result[mask] = styled[mask]
    return result


def get_dominant_colors(image: np.ndarray, k: int = 5) -> list[str]:
    small = resize_max(image, max_side=250)
    pixels = small.reshape((-1, 3)).astype(np.float32)
    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        40,
        0.2,
    )
    _, labels, centers = cv2.kmeans(
        pixels,
        k,
        None,
        criteria,
        3,
        cv2.KMEANS_PP_CENTERS,
    )
    centers = np.uint8(centers)
    counts = np.bincount(labels.flatten())
    sorted_indices = np.argsort(counts)[::-1]
    return [bgr_to_hex(centers[i]) for i in sorted_indices]


def create_palette_recommendations(image: np.ndarray) -> dict[str, Any]:
    dominant = get_dominant_colors(image, k=5)
    recommendations = [
        {
            'name': 'Warm Neutral',
            'colors': ['#F5EFE6', '#C9A66B', '#3A3A3A'],
        },
        {
            'name': 'Modern Calm',
            'colors': ['#E8EEF2', '#7A8B99', '#1F2933'],
        },
        {
            'name': 'Cozy Earth',
            'colors': ['#EFE3D0', '#A47148', '#4A3F35'],
        },
        {
            'name': 'Soft Minimal',
            'colors': ['#FAF9F6', '#D6CCC2', '#6B705C'],
        },
    ]
    return {
        'dominant_colors': dominant,
        'recommendations': recommendations,
    }
