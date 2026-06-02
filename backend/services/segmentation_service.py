from __future__ import annotations

from typing import Any

import numpy as np

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None

try:
    import torch
    _TORCH_AVAILABLE = True
except Exception:
    torch = None
    _TORCH_AVAILABLE = False


_DEEPLAB_MODEL: object | None = None


def _load_deeplab_model():
    """Lazily load a pretrained DeepLab model via torch.hub when available.

    Returns the model or None if it cannot be loaded.
    """
    global _DEEPLAB_MODEL
    if _DEEPLAB_MODEL is not None:
        return _DEEPLAB_MODEL
    if not _TORCH_AVAILABLE:
        return None
    try:
        # Use the torchvision hub source pinned to a compatible tag.
        # This mirrors the notebook approach and is guarded so missing
        # compiled torchvision ops won't break the API.
        try:
            _DEEPLAB_MODEL = torch.hub.load('pytorch/vision:v0.22.1', 'deeplabv3_resnet50', weights='DEFAULT')
        except Exception:
            # Fallback to older hub signature that may exist in some envs
            _DEEPLAB_MODEL = torch.hub.load('pytorch/vision', 'deeplabv3_resnet50', pretrained=True)
        _DEEPLAB_MODEL.eval()
        return _DEEPLAB_MODEL
    except Exception:
        _DEEPLAB_MODEL = None
        return None


def mask_to_vector_layers(mask: np.ndarray, name: str) -> list[dict[str, Any]]:
    if mask.dtype != np.uint8:
        mask_u8 = (mask.astype(np.uint8) * 255)
    else:
        mask_u8 = mask

    layers: list[dict[str, Any]] = []
    if cv2 is not None:
        contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for idx, contour in enumerate(contours):
            area = float(cv2.contourArea(contour))
            if area < 120:
                continue
            points = contour.reshape(-1, 2).tolist()
            layers.append(
                {
                    "id": f"{name}-{idx}",
                    "name": name,
                    "type": "polygon",
                    "points": points,
                    "area": area,
                }
            )
        if layers:
            return layers

    ys, xs = np.where(mask_u8 > 0)
    if len(xs) == 0:
        return []
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    return [
        {
            "id": f"{name}-0",
            "name": name,
            "type": "polygon",
            "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "area": float((x1 - x0) * (y1 - y0)),
        }
    ]


def _predict_foreground_mask(image_rgb: np.ndarray) -> np.ndarray:
    """Run DeepLab to produce a binary foreground mask.

    Returns boolean mask of shape (H, W) or None if model not available.
    """
    model = _load_deeplab_model()
    if model is None:
        return None
    # Preprocess (ImageNet normalization)
    img = image_rgb.astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    tensor = (img - mean) / std
    # HWC -> CHW and add batch
    tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
    try:
        inp = torch.from_numpy(tensor).float()
        with torch.no_grad():
            out = model(inp)['out']
        # out: N x C x H' x W' - resize to original size
        out = torch.nn.functional.interpolate(out, size=image_rgb.shape[:2], mode='bilinear', align_corners=False)
        labels = out.argmax(dim=1).squeeze(0).cpu().numpy()
        # Treat label 0 as background; foreground otherwise
        fg = labels != 0
        return fg
    except Exception:
        return None


def build_room_masks_from_model(image_rgb: np.ndarray) -> dict[str, np.ndarray] | None:
    """Attempt to build semantic masks using a pretrained DeepLab model.

    If the model is not available or prediction fails, returns None.
    The function attempts to split foreground into furniture vs floor vs wall
    using image-driven heuristics (centroid clustering) rather than fixed
    absolute thresholds.
    """
    fg = _predict_foreground_mask(image_rgb)
    if fg is None:
        return None
    h, w = fg.shape
    masks: dict[str, np.ndarray] = {}

    # Find connected components in foreground
    if cv2 is not None:
        contours, _ = cv2.findContours((fg.astype(np.uint8) * 255), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        comps = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < max(100, (h * w) * 0.0005):
                continue
            x, y, cw, ch = cv2.boundingRect(cnt)
            cy = y + ch / 2.0
            comps.append({'contour': cnt, 'area': area, 'bbox': (x, y, cw, ch), 'cy': cy})
    else:
        # Fallback: single component is all foreground
        ys, xs = np.where(fg)
        if len(xs) == 0:
            return None
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        comps = [{'contour': None, 'area': (x1 - x0) * (y1 - y0), 'bbox': (x0, y0, x1 - x0, y1 - y0), 'cy': (y0 + y1) / 2.0}]
        assign = np.array([1])

    if not comps:
        return None

    # Cluster components by vertical position to separate upper/background regions
    ys = np.array([c['cy'] / h for c in comps]).reshape(-1, 1)
    # K=2 clustering using simple 1D kmeans via numpy
    from math import inf

    # initialize centroids
    centroids = np.array([ys.min(), ys.max()]).reshape(2, 1)
    for _ in range(8):
        d = np.abs(ys - centroids.T)
        assign = d.argmin(axis=1)
        newc = np.array([ys[assign == k].mean() if np.any(assign == k) else centroids[k] for k in range(2)])
        if np.allclose(newc, centroids):
            break
        centroids = newc
    # cluster with higher mean y is the lower cluster (floor/furniture)
    cluster_means = np.array([ys[assign == k].mean() if np.any(assign == k) else -inf for k in range(2)])
    lower_cluster = cluster_means.argmax()

    furniture_mask = np.zeros((h, w), dtype=bool)
    floor_mask = np.zeros((h, w), dtype=bool)

    for idx, c in enumerate(comps):
        x, y, cw, ch = c['bbox']
        comp_mask = np.zeros((h, w), dtype=np.uint8)
        if cv2 is not None and c['contour'] is not None:
            cv2.drawContours(comp_mask, [c['contour']], -1, color=1, thickness=-1)
        else:
            comp_mask[y:y+ch, x:x+cw] = 1
        if assign[idx] == lower_cluster:
            # lower cluster components are either floor patches or furniture;
            # decide by bottom coverage and vertical extent.
            comp_bool = comp_mask.astype(bool)
            bottom_zone = comp_bool[int(h * 0.70):, :]
            bottom_ratio = bottom_zone.sum() / max(1, comp_bool.sum())
            if (y + ch) >= int(h * 0.94) or bottom_ratio > 0.60 or (ch / h) > 0.50:
                floor_mask |= comp_bool
            else:
                furniture_mask |= comp_bool
        else:
            # upper cluster -> likely wall or background; ignore small items
            pass

    # wall is remaining non-floor, non-furniture foreground region
    wall_mask = fg & (~floor_mask) & (~furniture_mask)

    masks['wall'] = wall_mask
    masks['floor'] = floor_mask
    masks['furniture'] = furniture_mask

    # sanity check: if the model-derived room masks are clearly wrong, use deterministic fallback
    total_pixels = h * w
    if (
        wall_mask.sum() < total_pixels * 0.02
        or wall_mask.sum() > total_pixels * 0.90
        or floor_mask.sum() < total_pixels * 0.02
        or floor_mask.sum() > total_pixels * 0.70
        or (furniture_mask.sum() > total_pixels * 0.45 and floor_mask.sum() < total_pixels * 0.10)
    ):
        fallback_masks = build_fallback_masks(h, w)
        if fallback_masks['wall'].sum() > 0 and fallback_masks['floor'].sum() > 0:
            return fallback_masks

    # Try to split furniture into coarse categories by bbox geometry
    # (wide -> sofa, narrow+tall -> lamp, square-ish -> table)
    if cv2 is not None:
        # iterate contours again for furniture components
        contours, _ = cv2.findContours((furniture_mask.astype(np.uint8) * 255), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for i, cnt in enumerate(contours):
            x, y, cw, ch = cv2.boundingRect(cnt)
            ar = cw / max(1, ch)
            submask = np.zeros((h, w), dtype=bool)
            cv2.drawContours(submask, [cnt], -1, color=1, thickness=-1)
            if ar > 1.2:
                masks.setdefault('sofa', np.zeros((h, w), dtype=bool))[:] |= submask
            elif ar < 0.6:
                masks.setdefault('lamp', np.zeros((h, w), dtype=bool))[:] |= submask
            else:
                masks.setdefault('table', np.zeros((h, w), dtype=bool))[:] |= submask
    else:
        masks.setdefault('sofa', np.zeros((h, w), dtype=bool))
        masks.setdefault('table', np.zeros((h, w), dtype=bool))
        masks.setdefault('lamp', np.zeros((h, w), dtype=bool))

    return masks


def build_fallback_masks(height: int, width: int) -> dict[str, np.ndarray]:
    # keep the old deterministic fallback for environments without models
    masks: dict[str, np.ndarray] = {}
    yy, xx = np.mgrid[0:height, 0:width]

    wall = yy < int(height * 0.58)
    floor = yy > int(height * 0.70)
    sofa = (
        (yy > int(height * 0.56))
        & (yy < int(height * 0.82))
        & (xx > int(width * 0.20))
        & (xx < int(width * 0.52))
    )
    table = (
        (yy > int(height * 0.56))
        & (yy < int(height * 0.72))
        & (xx > int(width * 0.54))
        & (xx < int(width * 0.74))
    )
    lamp = (
        (yy > int(height * 0.20))
        & (yy < int(height * 0.54))
        & (xx > int(width * 0.76))
        & (xx < int(width * 0.90))
    )
    furniture = sofa | table | lamp

    masks["wall"] = wall
    masks["floor"] = floor
    masks["sofa"] = sofa
    masks["table"] = table
    masks["lamp"] = lamp
    masks["furniture"] = furniture
    return masks
