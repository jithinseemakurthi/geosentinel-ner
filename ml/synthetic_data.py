"""
Synthetic data generator for M1, M2, and M3 landslide training pipelines.
Generates realistic distributions of terrain, precipitation, and report labels.
"""
from typing import List, Tuple

import numpy as np


def generate_m1_dataset(n_samples: int = 1000, random_state: int = 42) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Generate synthetic terrain & geology features for M1 Landslide Susceptibility.

    Features:
    - slope_deg (0-75)
    - aspect_deg (0-360)
    - elevation_m (100-3500)
    - profile_curvature (-0.1 to 0.1)
    - plan_curvature (-0.1 to 0.1)
    - topographic_wetness_index (1-18)
    - distance_to_fault_m (10-10000)
    - distance_to_stream_m (5-5000)
    - distance_to_road_m (5-5000)
    - geology_type (0-4 categorical)
    - land_cover (0-5 categorical)
    """
    rng = np.random.RandomState(random_state)

    slope = rng.uniform(5.0, 65.0, size=n_samples)
    aspect = rng.uniform(0.0, 360.0, size=n_samples)
    elevation = rng.uniform(200.0, 2800.0, size=n_samples)
    prof_curv = rng.normal(0.0, 0.03, size=n_samples)
    plan_curv = rng.normal(0.0, 0.03, size=n_samples)
    twi = rng.uniform(2.0, 15.0, size=n_samples)
    dist_fault = rng.exponential(1500.0, size=n_samples) + 50.0
    dist_stream = rng.exponential(500.0, size=n_samples) + 20.0
    dist_road = rng.exponential(800.0, size=n_samples) + 10.0
    geology = rng.randint(0, 5, size=n_samples).astype(float)
    landcover = rng.randint(0, 6, size=n_samples).astype(float)

    X = np.column_stack([
        slope, aspect, elevation, prof_curv, plan_curv,
        twi, dist_fault, dist_stream, dist_road, geology, landcover
    ])

    feature_names = [
        "slope_deg", "aspect_deg", "elevation_m", "profile_curvature", "plan_curvature",
        "topographic_wetness_index", "distance_to_fault_m", "distance_to_stream_m",
        "distance_to_road_m", "geology_type", "land_cover"
    ]

    # Ground truth probability based on slope, TWI, proximity to road/fault
    logit = (
        0.08 * (slope - 30.0)
        + 0.15 * (twi - 6.0)
        - 0.0008 * dist_road
        - 0.0005 * dist_fault
        + 0.5 * (geology == 2)
        - 0.8
    )
    prob = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.uniform(0.0, 1.0, size=n_samples) < prob).astype(int)

    return X, y, feature_names


def generate_m2_dataset(n_samples: int = 1200, random_state: int = 42) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Generate synthetic dynamic precipitation & soil data for M2 Early Warning.

    Features:
    - m1_susceptibility_score (0.0 - 1.0)
    - forecast_rainfall_24h_mm (0 - 300)
    - forecast_rainfall_48h_mm (0 - 500)
    - forecast_rainfall_72h_mm (0 - 700)
    - antecedent_rainfall_1d_mm (0 - 150)
    - antecedent_rainfall_3d_mm (0 - 350)
    - antecedent_rainfall_7d_mm (0 - 600)
    - antecedent_rainfall_14d_mm (0 - 1000)
    - soil_moisture_pct (10 - 95)
    - rainfall_intensity_max_mm_h (0 - 60)
    """
    rng = np.random.RandomState(random_state)

    m1_score = rng.beta(2.0, 2.0, size=n_samples)
    rain_24h = rng.exponential(35.0, size=n_samples)
    rain_48h = rain_24h + rng.exponential(30.0, size=n_samples)
    rain_72h = rain_48h + rng.exponential(25.0, size=n_samples)
    ant_1d = rng.exponential(20.0, size=n_samples)
    ant_3d = ant_1d + rng.exponential(40.0, size=n_samples)
    ant_7d = ant_3d + rng.exponential(70.0, size=n_samples)
    ant_14d = ant_7d + rng.exponential(100.0, size=n_samples)
    soil_moisture = np.clip(15.0 + 0.08 * ant_7d + rng.normal(0, 5, size=n_samples), 10.0, 95.0)
    rain_intensity = np.clip(rain_24h / 12.0 + rng.exponential(4.0, size=n_samples), 0.0, 80.0)

    X = np.column_stack([
        m1_score, rain_24h, rain_48h, rain_72h,
        ant_1d, ant_3d, ant_7d, ant_14d,
        soil_moisture, rain_intensity
    ])

    feature_names = [
        "m1_susceptibility_score", "forecast_rainfall_24h_mm", "forecast_rainfall_48h_mm",
        "forecast_rainfall_72h_mm", "antecedent_rainfall_1d_mm", "antecedent_rainfall_3d_mm",
        "antecedent_rainfall_7d_mm", "antecedent_rainfall_14d_mm", "soil_moisture_pct",
        "rainfall_intensity_max_mm_h"
    ]

    # Risk calculation: combined hazard index
    hazard_index = (
        1.8 * m1_score
        + 0.02 * rain_24h
        + 0.012 * ant_3d
        + 0.008 * ant_7d
        + 0.025 * (soil_moisture - 40.0)
        + 0.04 * rain_intensity
        - 2.5
    )
    prob = 1.0 / (1.0 + np.exp(-hazard_index))
    y = (rng.uniform(0.0, 1.0, size=n_samples) < prob).astype(int)

    return X, y, feature_names


M3_CLASSES = ["crack", "bulge", "debris", "rockfall", "road_block", "normal"]


def generate_m3_dataset(n_samples: int = 600, random_state: int = 42) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Generate synthetic feature embeddings and multi-class labels for M3 Citizen CV Triage.
    Simulates pre-trained CNN / MobileNetV3 feature vectors (e.g., 64-dim embeddings).
    """
    rng = np.random.RandomState(random_state)
    n_classes = len(M3_CLASSES)
    n_features = 64

    # Class centers in embedding space
    centers = rng.normal(0.0, 2.0, size=(n_classes, n_features))

    y = rng.randint(0, n_classes, size=n_samples)
    X = np.zeros((n_samples, n_features), dtype=np.float32)
    for i in range(n_samples):
        cls_idx = y[i]
        X[i] = centers[cls_idx] + rng.normal(0.0, 0.8, size=n_features)

    return X, y, M3_CLASSES
