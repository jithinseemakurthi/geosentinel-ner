"""
M1 Spatial Feature Extraction Pipeline.
Extracts geomorphometric and geological features from DEM derivatives and vector GIS layers.
"""
from typing import Any, Dict, List

import numpy as np


def compute_topographic_wetness_index(catchment_area: np.ndarray, slope_deg: np.ndarray) -> np.ndarray:
    """
    Compute Topographic Wetness Index: TWI = ln(a / tan(beta))
    where `a` is specific catchment area and `beta` is slope in radians.
    """
    slope_rad = np.radians(np.clip(slope_deg, 0.5, 89.0))
    tan_slope = np.tan(slope_rad)
    catchment_safe = np.clip(catchment_area, 1.0, None)
    return np.log(catchment_safe / tan_slope)


def compute_stream_power_index(catchment_area: np.ndarray, slope_deg: np.ndarray) -> np.ndarray:
    """
    Compute Stream Power Index: SPI = a * tan(beta)
    """
    slope_rad = np.radians(np.clip(slope_deg, 0.1, 89.0))
    tan_slope = np.tan(slope_rad)
    return catchment_area * tan_slope


def extract_spatial_features(raw_zone_data: List[Dict[str, Any]]) -> np.ndarray:
    """
    Extract normalized feature matrix for M1 Susceptibility inference.
    """
    features = []
    for zone in raw_zone_data:
        slope = float(zone.get("slope_deg", 25.0))
        aspect = float(zone.get("aspect_deg", 180.0))
        elevation = float(zone.get("elevation_m", 800.0))
        prof_curv = float(zone.get("profile_curvature", 0.0))
        plan_curv = float(zone.get("plan_curvature", 0.0))
        twi = float(zone.get("topographic_wetness_index", 7.5))
        dist_fault = float(zone.get("distance_to_fault_m", 2000.0))
        dist_stream = float(zone.get("distance_to_stream_m", 500.0))
        dist_road = float(zone.get("distance_to_road_m", 300.0))
        geology = float(zone.get("geology_type", 1.0))
        land_cover = float(zone.get("land_cover", 2.0))

        features.append([
            slope, aspect, elevation, prof_curv, plan_curv,
            twi, dist_fault, dist_stream, dist_road, geology, land_cover
        ])
    return np.array(features, dtype=np.float32)
