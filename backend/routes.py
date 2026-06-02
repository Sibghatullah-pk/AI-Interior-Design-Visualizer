from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from flask import Blueprint, Flask, jsonify, request, send_from_directory
from PIL import Image

from backend.config import FURNITURE_CATALOG, OUTPUT_DIR, PREVIEW_DIR, STYLE_THEMES, UPLOAD_DIR, ensure_storage_dirs
from backend.services.image_service import (
    bbox_from_mask,
    mask_to_png_data_url,
    parse_image_request,
    recolor_area,
    apply_furniture_style,
)
from backend.services.palette_service import extract_palette, suggest_wall_palettes
from backend.services.redesign_service import apply_style_theme, build_design_payload
from backend.services import segmentation_service
from backend.services.storage_service import load_design_payload, save_design_payload
from backend.services.palette_service import generate_recommendation_palettes
from backend.services.redesign_service import recolor_region_preserve_lighting
from backend.services.analytics_service import compute_analytics
from backend.realtime import emit_to_client
from backend.services.palette_service import rgb_to_hex


api = Blueprint("api", __name__, url_prefix="/api")

ROOM_TYPES = ["Living Room", "Bedroom", "Kitchen", "Office", "Bathroom", "Dining Room"]


def _client_id_from_request(body: dict[str, Any] | None = None) -> str | None:
    body = body or {}
    return request.headers.get("X-Client-ID") or request.args.get("clientId") or body.get("clientId")


def _theme_options() -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for key, theme in STYLE_THEMES.items():
        options.append({
            "key": key,
            "label": key.replace("_", " ").title(),
            "wall": rgb_to_hex(theme.get("wall", [238, 232, 222])),
            "accent": rgb_to_hex(theme.get("accent", [124, 145, 133])),
        })
    return options


def make_design_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def save_preview_image(image_rgb: np.ndarray, design_id: str) -> str:
    ensure_storage_dirs()
    from io import BytesIO
    import base64

    # If configured to persist previews, save to PREVIEW_DIR and return filename.
    if getattr(__import__('backend.config'), 'SAVE_PREVIEWS', False):
        filename = f"preview_{design_id}.png"
        path = PREVIEW_DIR / filename
        Image.fromarray(image_rgb).save(path)
        return filename

    # Otherwise, return a data URL so frontend can load without touching disk.
    buff = BytesIO()
    Image.fromarray(image_rgb).save(buff, format='PNG')
    b64 = base64.b64encode(buff.getvalue()).decode('ascii')
    return f"data:image/png;base64,{b64}"


def add_api_prefix_to_url(url: str | None) -> str | None:
    if not url:
        return url
    if url.startswith("/api/"):
        return url
    if url.startswith("/"):
        return f"/api{url}"
    return url


def combine_selected_masks(masks: dict[str, Any], selected_ids: list[Any]) -> np.ndarray | None:
    if not selected_ids:
        return None

    ordered_keys = list(masks.keys())
    combined: np.ndarray | None = None

    for item in selected_ids:
        mask = None
        if isinstance(item, str) and item in masks:
            mask = masks[item]
        elif isinstance(item, int) and 0 <= item < len(ordered_keys):
            mask = masks[ordered_keys[item]]
        elif isinstance(item, str) and item.isdigit():
            idx = int(item)
            if 0 <= idx < len(ordered_keys):
                mask = masks[ordered_keys[idx]]

        if mask is None:
            continue

        if combined is None:
            combined = mask.copy()
        else:
            combined = combined | mask

    return combined


@api.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "message": "Backend is running"
    })


@api.route("/ui-config", methods=["GET"])
def ui_config():
    themes = _theme_options()
    default_theme = themes[0]["key"] if themes else "japandi"
    default_target_color = themes[0]["wall"] if themes else "#e8dfd5"
    return jsonify({
        "styleThemes": themes,
        "roomTypes": ROOM_TYPES,
        "catalog": FURNITURE_CATALOG,
        "defaultTheme": default_theme,
        "defaultTargetColor": default_target_color,
    })


@api.route("/analytics", methods=["GET"])
def analytics():
    try:
        ensure_storage_dirs()
        return jsonify(compute_analytics(OUTPUT_DIR))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@api.route("/palette", methods=["POST"])
def palette():
    try:
        ensure_storage_dirs()
        image_rgb, image_source = parse_image_request(request, UPLOAD_DIR)

        room_palette = extract_palette(image_rgb, k=5)
        recommendations = suggest_wall_palettes(room_palette)

        image_source["url"] = add_api_prefix_to_url(image_source.get("url"))

        return jsonify({
            "imageSource": image_source,
            "roomPalette": room_palette,
            "recommendations": recommendations,
            "palette": [swatch["hex"] for swatch in room_palette.get("swatches", [])],
        })

    except Exception as exc:
        return jsonify({
            "error": str(exc)
        }), 400


@api.route("/redesign", methods=["POST"])
def redesign():
    try:
        ensure_storage_dirs()

        body = request.get_json(silent=True) or {}
        client_id = _client_id_from_request(body)
        selected_theme = body.get("styleTheme") or body.get("theme") or "japandi"
        wall_override = body.get("wallColor") or body.get("targetColor")

        image_rgb, image_source = parse_image_request(request, UPLOAD_DIR)

        height, width = image_rgb.shape[:2]
        emit_to_client("segmentation_started", {"clientId": client_id, "stage": "segment", "progress": 0}, client_id)
        # segmentation: attempt model-backed masks, fall back to deterministic masks
        try:
            masks = segmentation_service.build_room_masks_from_model(image_rgb)
            if masks is None:
                masks = segmentation_service.build_fallback_masks(height, width)
        except Exception:
            masks = segmentation_service.build_fallback_masks(height, width)
        emit_to_client("segmentation_progress", {"clientId": client_id, "stage": "segment", "progress": 60}, client_id)

        vector_layers: dict[str, list[dict[str, Any]]] = {
            name: segmentation_service.mask_to_vector_layers(mask, name)
            for name, mask in masks.items()
        }
        emit_to_client(
            "segmentation_done",
            {
                "clientId": client_id,
                "stage": "segment",
                "progress": 100,
                "vectorLayers": vector_layers,
                "previewPartial": add_api_prefix_to_url(image_source.get("url")),
            },
            client_id,
        )

        emit_to_client("recolor_started", {"clientId": client_id, "stage": "recolor", "progress": 0}, client_id)
        room_palette = extract_palette(image_rgb, k=5)
        palette_suggestions = suggest_wall_palettes(room_palette)

        redesigned_rgb = apply_style_theme(
            image_rgb=image_rgb,
            masks=masks,
            theme_name=selected_theme,
            wall_override=wall_override,
        )

        design_id = make_design_id()
        preview_ref = save_preview_image(redesigned_rgb, design_id)

        image_source["url"] = add_api_prefix_to_url(image_source.get("url"))

        payload = build_design_payload(
            design_id=design_id,
            image_shape=image_rgb.shape,
            image_source=image_source,
            masks=masks,
            vector_layers=vector_layers,
            room_palette=room_palette,
            palette_suggestions=palette_suggestions,
            selected_theme=selected_theme,
        )
        # preview_ref may be a filename or a data URL depending on config
        if isinstance(preview_ref, str) and preview_ref.startswith("data:image"):
            preview_url = preview_ref
            payload["previewUrl"] = preview_url
        else:
            preview_url = f"/api/previews/{preview_ref}"
            payload["previewUrl"] = preview_url

        emit_to_client(
            "recolor_done",
            {
                "clientId": client_id,
                "stage": "recolor",
                "progress": 100,
                "previewUrl": preview_url,
                "designId": design_id,
            },
            client_id,
        )

        save_design_payload(payload, OUTPUT_DIR)

        return jsonify({
            "id": design_id,
            "designId": design_id,
            "previewUrl": preview_url,
            "imageUrl": image_source.get("url"),
            "roomPalette": room_palette,
            "recommendations": palette_suggestions,
            "vectorLayers": vector_layers,
            "payload": payload,
            "message": "Redesign generated successfully",
        })

    except Exception as exc:
        return jsonify({
            "error": str(exc)
        }), 400


@api.route("/segment", methods=["POST"])
def segment():
    try:
        ensure_storage_dirs()
        body = request.get_json(silent=True) or {}
        client_id = _client_id_from_request(body)
        emit_to_client("segmentation_started", {"clientId": client_id, "stage": "segment", "progress": 0}, client_id)
        image_rgb, image_source = parse_image_request(request, UPLOAD_DIR)

        height, width = image_rgb.shape[:2]
        try:
            masks = segmentation_service.build_room_masks_from_model(image_rgb)
            if masks is None:
                masks = segmentation_service.build_fallback_masks(height, width)
        except Exception:
            masks = segmentation_service.build_fallback_masks(height, width)
        emit_to_client("segmentation_progress", {"clientId": client_id, "stage": "segment", "progress": 70}, client_id)

        vector_layers: dict[str, list[dict[str, Any]]] = {
            name: segmentation_service.mask_to_vector_layers(mask, name)
            for name, mask in masks.items()
        }

        emit_to_client(
            "segmentation_done",
            {
                "clientId": client_id,
                "stage": "segment",
                "progress": 100,
                "vectorLayers": vector_layers,
                "previewPartial": add_api_prefix_to_url(image_source.get("url")),
            },
            client_id,
        )

        image_source["url"] = add_api_prefix_to_url(image_source.get("url"))

        mask_items = []
        region_order = [
            ("wall", "Wall", "wall"),
            ("floor", "Floor", "floor"),
            ("furniture", "Furniture", "object/furniture"),
            ("sofa", "Sofa", "object/furniture"),
            ("table", "Table", "object/furniture"),
            ("lamp", "Lamp", "object/furniture"),
        ]
        for index, (key, name, mask_type) in enumerate(region_order):
            if key not in masks:
                continue
            mask = masks[key]
            mask_items.append({
                "id": key,
                "name": name,
                "type": mask_type,
                "area": int(mask.sum()),
                "bbox": bbox_from_mask(mask),
                "mask_png": mask_to_png_data_url(mask, index),
            })

        return jsonify({
            "status": "success",
            "image_id": image_source.get("filename", ""),
            "image_url": image_source.get("url"),
            "mask_count": len(mask_items),
            "masks": mask_items,
            "imageSource": image_source,
            "vectorLayers": vector_layers,
            "regions": {
                name: {
                    "pixelCount": int(mask.sum()),
                    "coverage": round(float(mask.mean()), 4),
                }
                for name, mask in masks.items()
            }
        })

    except Exception as exc:
        return jsonify({
            "error": str(exc)
        }), 400


@api.route("/recolor", methods=["POST"])
def recolor():
    try:
        ensure_storage_dirs()
        body = request.get_json(silent=True) or {}
        client_id = _client_id_from_request(body)
        emit_to_client("recolor_started", {"clientId": client_id, "stage": "recolor", "progress": 0}, client_id)
        image_rgb, image_source = parse_image_request(request, UPLOAD_DIR)
        target = body.get('targetColor') or request.form.get('targetColor')
        mask_ids = body.get('mask_ids') or body.get('maskIds') or []
        region = body.get('region') or request.form.get('region')
        if not target:
            raise ValueError('Provide targetColor as hex string like #aabbcc')

        try:
            masks = segmentation_service.build_room_masks_from_model(image_rgb)
            if masks is None:
                masks = segmentation_service.build_fallback_masks(image_rgb.shape[0], image_rgb.shape[1])
        except Exception:
            masks = segmentation_service.build_fallback_masks(image_rgb.shape[0], image_rgb.shape[1])

        selected_mask = None
        selected_region = region
        if isinstance(mask_ids, list) and mask_ids:
            selected_mask = combine_selected_masks(masks, mask_ids)
            selected_region = ','.join(str(i) for i in mask_ids)
        elif region:
            if region not in masks:
                raise ValueError(f'Region "{region}" not found in segmentation masks')
            selected_mask = masks[region]
        else:
            raise ValueError('Provide region or mask_ids to recolor')

        if selected_mask is None:
            raise ValueError('No valid mask selected for recolor')

        from backend.services.palette_service import hex_to_rgb
        tgt_rgb = hex_to_rgb(target)
        recolored = recolor_area(image_rgb, selected_mask, target)

        from io import BytesIO
        import base64
        buff = BytesIO()
        Image.fromarray(recolored).save(buff, format='PNG')
        b64 = base64.b64encode(buff.getvalue()).decode('ascii')
        preview_url = f'data:image/png;base64,{b64}'
        emit_to_client(
            "recolor_done",
            {
                "clientId": client_id,
                "stage": "recolor",
                "progress": 100,
                "previewUrl": preview_url,
                "region": selected_region,
            },
            client_id,
        )
        return jsonify({
            'previewUrl': preview_url,
            'region': selected_region
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


@api.route('/recommend', methods=['POST'])
def recommend():
    try:
        body = request.get_json(silent=True) or {}
        base = body.get('baseColor') or body.get('color')
        if not base:
            return jsonify({'error': 'Provide baseColor hex in JSON body'}), 400
        palettes = generate_recommendation_palettes(base)
        return jsonify({'base': base, 'palettes': palettes})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


@api.route("/designs/save", methods=["POST"])
def save_design():
    ensure_storage_dirs()
    body = request.get_json(silent=True) or {}

    design_id = body.get("id") or make_design_id()
    body["id"] = design_id

    save_design_payload(body, OUTPUT_DIR)

    return jsonify({
        "id": design_id,
        "shareUrl": f"/api/designs/{design_id}",
        "share_url": f"/api/designs/{design_id}",
    })


@api.route("/designs/<design_id>", methods=["GET"])
def get_design(design_id: str):
    payload = load_design_payload(design_id, OUTPUT_DIR)

    if payload is None:
        return jsonify({
            "error": "Design not found"
        }), 404

    return jsonify(payload)


@api.route("/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename: str):
    return send_from_directory(UPLOAD_DIR, filename)


@api.route("/previews/<path:filename>", methods=["GET"])
def serve_preview(filename: str):
    return send_from_directory(PREVIEW_DIR, filename)


def register_routes(app: Flask) -> None:
    ensure_storage_dirs()
    app.register_blueprint(api)