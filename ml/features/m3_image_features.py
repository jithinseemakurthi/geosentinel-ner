"""
M3 Image Preprocessing & Augmentation Pipeline.
Prepares citizen landslide report photos for classification.
"""
from typing import Optional, Tuple

import numpy as np


class ImageTransformPipeline:
    """Preprocesses and normalizes image arrays for MobileNetV3 / ResNet inference."""

    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self, target_size: Tuple[int, int] = (224, 224)):
        self.target_size = target_size

    def preprocess(self, img_array: np.ndarray) -> np.ndarray:
        """
        Normalize and transpose HWC -> CHW format.
        """
        img = img_array.astype(np.float32)
        if img.max() > 1.0:
            img /= 255.0

        # Rescale / normalise with ImageNet stats
        norm_img = (img - self.MEAN) / self.STD
        # Transpose from (H, W, C) to (C, H, W)
        return np.transpose(norm_img, (2, 0, 1))


def preprocess_image_array(img: Optional[np.ndarray] = None) -> np.ndarray:
    """Helper to convert image or generate dummy test tensor."""
    if img is None:
        img = np.random.randint(0, 256, size=(224, 224, 3), dtype=np.uint8)
    pipeline = ImageTransformPipeline()
    return pipeline.preprocess(img)
