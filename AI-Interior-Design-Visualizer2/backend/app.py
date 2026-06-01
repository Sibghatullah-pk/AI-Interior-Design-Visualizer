import base64
import os
import uuid

import cv2
import numpy as np
from flask import Flask, jsonify, request, send_from_directory

from utils.sam_service import get_mask_generator, DEVICE
from utils.image_ops import (
    resize_max,
    bbox_from_mask,
    mask_to_png_data_url,
    build_basic_room_masks,
    recolor_area,
    apply_furniture_style,
    create_palette_recommendations,
)

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)

UPLOAD_DIR = os.path.join(PROJECT_DIR, "uploads")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "outputs")
MASK_DIR = os.path.join(PROJECT_DIR, "masks")
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MASK_DIR, exist_ok=True)

app = Flask(__name__)


@app.route("/")
def home():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/outputs/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename)


def image_path(image_id):
    return os.path.join(UPLOAD_DIR, image_id + ".png")


def mask_path(image_id):
    return os.path.join(MASK_DIR, image_id + ".npz")


def load_image_and_masks(image_id):
    img_path = image_path(image_id)
    m_path = mask_path(image_id)

    if not os.path.exists(img_path):
        raise FileNotFoundError("Image not found.")

    if not os.path.exists(m_path):
        raise FileNotFoundError("Masks not found.")

    image = cv2.imread(img_path)
    masks = np.load(m_path)["masks"].astype(bool)

    return image, masks


def combine_selected_masks(masks, selected_ids):
    valid_ids = []

    for item in selected_ids:
        try:
            idx = int(item)
            if 0 <= idx < len(masks):
                valid_ids.append(idx)
        except ValueError:
            pass

    if not valid_ids:
        return None

    return np.any(masks[valid_ids], axis=0)


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "message": "AI Interior Design Visualizer backend running",
        "device": DEVICE,
    })


@app.route("/api/catalog")
def catalog():
    return jsonify({
        "status": "success",
        "catalog": [
            {"id": "sofa", "name": "Sofa", "type": "furniture"},
            {"id": "table", "name": "Table", "type": "furniture"},
            {"id": "lamp", "name": "Lamp", "type": "decor"},
            {"id": "plant", "name": "Plant", "type": "decor"},
            {"id": "rug", "name": "Rug", "type": "decor"},
        ]
    })


@app.route("/api/upload", methods=["POST"])
@app.route("/api/segment", methods=["POST"])
def upload_room():
    file = request.files.get("room")

    if file is None:
        return jsonify({"error": "No image uploaded. Field name must be room."}), 400

    raw = np.frombuffer(file.read(), np.uint8)
    image = cv2.imdecode(raw, cv2.IMREAD_COLOR)

    if image is None:
        return jsonify({"error": "Invalid image file."}), 400

    image = resize_max(image, max_side=650)

    image_id = str(uuid.uuid4())
    image_filename = image_id + ".png"
    img_path = image_path(image_id)

    cv2.imwrite(img_path, image)

    h, w = image.shape[:2]

    print("Generating basic wall/floor masks...")
    wall_mask, floor_mask = build_basic_room_masks(h, w)

    all_masks = [wall_mask, floor_mask]

    mask_items = [
        {
            "id": 0,
            "name": "Suggested Wall Area",
            "type": "wall",
            "area": int(wall_mask.sum()),
            "bbox": bbox_from_mask(wall_mask),
            "mask_png": mask_to_png_data_url(wall_mask, 0),
        },
        {
            "id": 1,
            "name": "Suggested Floor Area",
            "type": "floor",
            "area": int(floor_mask.sum()),
            "bbox": bbox_from_mask(floor_mask),
            "mask_png": mask_to_png_data_url(floor_mask, 1),
        },
    ]

    print("Generating SAM masks. This can be slow on CPU...")
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    mask_generator = get_mask_generator()
    sam_results = mask_generator.generate(rgb_image)

    sam_results = sorted(sam_results, key=lambda x: x["area"], reverse=True)

    max_sam_masks = 15

    for item in sam_results:
        if len(all_masks) >= max_sam_masks + 2:
            break

        mask = item["segmentation"].astype(bool)

        if mask.sum() < 700:
            continue

        mask_id = len(all_masks)
        all_masks.append(mask)

        mask_items.append({
            "id": mask_id,
            "name": f"SAM Object Mask {mask_id}",
            "type": "object/furniture",
            "area": int(mask.sum()),
            "bbox": bbox_from_mask(mask),
            "mask_png": mask_to_png_data_url(mask, mask_id),
        })

    masks_array = np.stack(all_masks).astype(np.uint8)
    np.savez_compressed(mask_path(image_id), masks=masks_array)

    return jsonify({
        "status": "success",
        "image_id": image_id,
        "image_url": "/uploads/" + image_filename,
        "mask_count": len(mask_items),
        "masks": mask_items,
    })


@app.route("/api/palette", methods=["POST"])
def palette():
    data = request.get_json(force=True)
    image_id = data.get("image_id")

    if not image_id:
        return jsonify({"error": "image_id required."}), 400

    img_path = image_path(image_id)

    if not os.path.exists(img_path):
        return jsonify({"error": "Image not found."}), 404

    image = cv2.imread(img_path)
    result = create_palette_recommendations(image)

    return jsonify(result)


@app.route("/api/recolor", methods=["POST"])
def recolor():
    data = request.get_json(force=True)

    image_id = data.get("image_id")
    mask_ids = data.get("mask_ids", [])
    color = data.get("color", "#FFFFFF")

    if not image_id:
        return jsonify({"error": "image_id required."}), 400

    image, masks = load_image_and_masks(image_id)
    selected_mask = combine_selected_masks(masks, mask_ids)

    if selected_mask is None:
        return jsonify({"error": "Select at least one mask."}), 400

    result = recolor_area(image, selected_mask, color)

    output_name = image_id + "_recolor.png"
    output_path = os.path.join(OUTPUT_DIR, output_name)
    cv2.imwrite(output_path, result)

    return jsonify({
        "status": "success",
        "result_url": "/outputs/" + output_name,
    })


@app.route("/api/style", methods=["POST"])
def style():
    data = request.get_json(force=True)

    image_id = data.get("image_id")
    mask_ids = data.get("mask_ids", [])
    style_name = data.get("style", "modern")

    if not image_id:
        return jsonify({"error": "image_id required."}), 400

    image, masks = load_image_and_masks(image_id)
    selected_mask = combine_selected_masks(masks, mask_ids)

    if selected_mask is None:
        return jsonify({"error": "Select at least one furniture/object mask."}), 400

    result = apply_furniture_style(image, selected_mask, style_name)

    output_name = image_id + "_style_" + style_name + ".png"
    output_path = os.path.join(OUTPUT_DIR, output_name)
    cv2.imwrite(output_path, result)

    return jsonify({
        "status": "success",
        "result_url": "/outputs/" + output_name,
    })


@app.route("/api/redesign", methods=["POST"])
def redesign():
    data = request.get_json(force=True)
    mode = data.get("mode", "color")

    if mode == "style":
        return style()

    return recolor()


@app.route("/api/save-design", methods=["POST"])
@app.route("/api/designs/save", methods=["POST"])
def save_design():
    data = request.get_json(force=True)
    data_url = data.get("data_url")

    if not data_url:
        return jsonify({"error": "data_url required."}), 400

    try:
        encoded = data_url.split(",", 1)[1]
        binary = base64.b64decode(encoded)
    except Exception:
        return jsonify({"error": "Invalid data URL."}), 400

    output_name = "final_design_" + str(uuid.uuid4()) + ".png"
    output_path = os.path.join(OUTPUT_DIR, output_name)

    with open(output_path, "wb") as f:
        f.write(binary)

    return jsonify({
        "status": "success",
        "saved_url": "/outputs/" + output_name,
    })


if __name__ == "__main__":
    print("Starting backend...")
    print("Device:", DEVICE)
    app.run(host="127.0.0.1", port=5000, debug=True)
