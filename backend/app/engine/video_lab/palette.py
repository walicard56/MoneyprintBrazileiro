"""Dominant color extraction from a thumbnail (Etapa 3) — k-means in BGR
space, returned as hex strings ordered by cluster size (most dominant first)."""

from __future__ import annotations


def dominant_colors(image_path: str, *, n_colors: int = 4) -> list[str]:
    """Returns up to ``n_colors`` dominant colors as ``"#rrggbb"`` strings.
    Returns ``[]`` if the image can't be read."""
    import cv2
    import numpy as np

    image = cv2.imread(image_path)
    if image is None:
        return []

    pixels = image.reshape(-1, 3).astype(np.float32)
    k = max(1, min(n_colors, len(pixels)))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _compactness, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3, cv2.KMEANS_RANDOM_CENTERS)

    counts = np.bincount(labels.flatten(), minlength=k)
    order = np.argsort(-counts)

    hex_colors: list[str] = []
    for i in order:
        b, g, r = (int(c) for c in centers[i])
        hex_colors.append(f"#{r:02x}{g:02x}{b:02x}")
    return hex_colors
