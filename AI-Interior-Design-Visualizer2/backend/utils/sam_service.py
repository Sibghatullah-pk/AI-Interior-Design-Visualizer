import os
import torch
from segment_anything import sam_model_registry, SamAutomaticMaskGenerator

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKPOINT_PATH = os.path.join(PROJECT_DIR, "checkpoints", "sam_vit_b_01ec64.pth")

MODEL_TYPE = "vit_b"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

_mask_generator = None


def get_mask_generator():
    global _mask_generator

    if _mask_generator is not None:
        return _mask_generator

    if not os.path.exists(CHECKPOINT_PATH):
        raise FileNotFoundError(
            "SAM checkpoint not found. Put sam_vit_b_01ec64.pth inside checkpoints folder."
        )

    torch.set_num_threads(2)

    print("Loading SAM model...")
    print("Device:", DEVICE)

    sam = sam_model_registry[MODEL_TYPE](checkpoint=CHECKPOINT_PATH)
    sam.to(device=DEVICE)

    _mask_generator = SamAutomaticMaskGenerator(
        model=sam,
        points_per_side=12,
        pred_iou_thresh=0.86,
        stability_score_thresh=0.90,
        crop_n_layers=0,
        min_mask_region_area=700,
    )

    print("SAM model loaded successfully.")
    return _mask_generator