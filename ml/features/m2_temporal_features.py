"""
M2 Temporal Feature Extraction Pipeline.
Calculates Antecedent Precipitation Indices (API), rainfall intensity, and cumulative forecasts.
"""
from typing import Any, Dict, List

import numpy as np


def compute_antecedent_precipitation_index(
    daily_rainfall_mm: List[float],
    decay_factor: float = 0.84,
    days: int = 14,
) -> float:
    """
    Compute Antecedent Precipitation Index: API_t = sum_{i=1}^N (k^i * P_{t-i})
    where `k` is decay factor (typically 0.80 - 0.90) and `P_{t-i}` is daily rainfall.
    """
    if not daily_rainfall_mm:
        return 0.0
    history = daily_rainfall_mm[-days:]
    weights = [decay_factor ** (len(history) - idx) for idx in range(len(history))]
    return float(sum(p * w for p, w in zip(history, weights)))


def compute_dynamic_features(raw_sensor_weather: List[Dict[str, Any]]) -> np.ndarray:
    """
    Extract feature matrix for M2 Dynamic Risk inference.
    """
    features = []
    for item in raw_sensor_weather:
        m1_score = float(item.get("m1_susceptibility_score", 0.5))
        forecast_24h = float(item.get("forecast_rainfall_24h_mm", 0.0))
        forecast_48h = float(item.get("forecast_rainfall_48h_mm", forecast_24h * 1.5))
        forecast_72h = float(item.get("forecast_rainfall_72h_mm", forecast_48h * 1.3))
        ant_1d = float(item.get("antecedent_rainfall_1d_mm", 0.0))
        ant_3d = float(item.get("antecedent_rainfall_3d_mm", ant_1d * 2.0))
        ant_7d = float(item.get("antecedent_rainfall_7d_mm", ant_3d * 1.8))
        ant_14d = float(item.get("antecedent_rainfall_14d_mm", ant_7d * 1.5))
        soil_moisture = float(item.get("soil_moisture_pct", 35.0))
        rain_intensity = float(item.get("rainfall_intensity_max_mm_h", forecast_24h / 12.0))

        features.append([
            m1_score, forecast_24h, forecast_48h, forecast_72h,
            ant_1d, ant_3d, ant_7d, ant_14d,
            soil_moisture, rain_intensity
        ])
    return np.array(features, dtype=np.float32)
