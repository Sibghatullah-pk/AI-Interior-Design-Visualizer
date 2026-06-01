import base64
import cv2
import numpy as np


def resize_max(image, max_side=650):
    h, w = image.shape[:2]

    if max(h, w) <= max_side:
        return image

    scale = max_side / max(h, w)
    new_w = int(w * scale)
    new_h = int(h * scale)

    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def bbox_from_mask(mask):
    ys, xs = np.where(mask)

    if len(xs) == 0 or len(ys) == 0:
        return [0, 0, 0, 0]

    x1, x2 = xs.min(), xs.max()
    y1, y2 = ys.min(), ys.max()

    return [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]


def mask_to_png_data_url(mask, index=0):
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

    success, buffer = cv2.imencode(".png", overlay)

    if not success:
        return ""

    encoded = base64.b64encode(buffer).decode("utf-8")
    return "data:image/png;base64," + encoded


def build_basic_room_masks(height, width):
    wall_mask = np.zeros((height, width), dtype=bool)
    floor_mask = np.zeros((height, width), dtype=bool)

    wall_end = int(height * 0.62)

    wall_mask[:wall_end, :] = True
    floor_mask[wall_end:, :] = True

    return wall_mask, floor_mask


def hex_to_bgr(hex_color):
    hex_color = hex_color.replace("#", "")

    if len(hex_color) != 6:
        return np.array([255, 255, 255], dtype=np.uint8)

    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    return np.array([b, g, r], dtype=np.uint8)


def bgr_to_hex(bgr):
    b, g, r = [int(x) for x in bgr]
    return f"#{r:02X}{g:02X}{b:02X}"


def recolor_area(image, mask, hex_color, alpha=0.55):
    result = image.copy()
    color = hex_to_bgr(hex_color)

    color_layer = image.copy()
    color_layer[mask] = color

    blended = cv2.addWeighted(color_layer, alpha, image, 1 - alpha, 0)
    result[mask] = blended[mask]

    return result


def apply_furniture_style(image, mask, style_name):
    style_name = style_name.lower().strip()

    h, w = image.shape[:2]
    texture = np.zeros_like(image)

    if style_name == "wood":
        texture[:] = hex_to_bgr("#9B6A3C")
        for y in range(0, h, 12):
            cv2.line(texture, (0, y), (w, y), hex_to_bgr("#5C3A21").tolist(), 2)

    elif style_name == "modern":
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray_3 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        base = np.full_like(image, hex_to_bgr("#D8DEE9"))
        texture = cv2.addWeighted(gray_3, 0.6, base, 0.4, 0)

    elif style_name == "minimal":
        texture[:] = hex_to_bgr("#E8E2D6")

    elif style_name == "velvet":
        texture[:] = hex_to_bgr("#5B2C6F")
        noise = np.random.randint(0, 35, image.shape, dtype=np.uint8)
        texture = cv2.add(texture, noise)
        texture = cv2.GaussianBlur(texture, (9, 9), 0)

    else:
        texture[:] = hex_to_bgr("#C0C0C0")

    result = image.copy()
    styled = cv2.addWeighted(image, 0.25, texture, 0.75, 0)
    result[mask] = styled[mask]

    return result


def get_dominant_colors(image, k=5):
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


def create_palette_recommendations(image):
    dominant = get_dominant_colors(image, k=5)

    recommendations = [
        {
            "name": "Warm Neutral",
            "colors": ["#F5EFE6", "#C9A66B", "#3A3A3A"],
        },
        {
            "name": "Modern Calm",
            "colors": ["#E8EEF2", "#7A8B99", "#1F2933"],
        },
        {
            "name": "Cozy Earth",
            "colors": ["#EFE3D0", "#A47148", "#4A3F35"],
        },
        {
            "name": "Soft Minimal",
            "colors": ["#FAF9F6", "#D6CCC2", "#6B705C"],
        },
    ]

    return {
        "dominant_colors": dominant,
        "recommendations": recommendations,
    }
