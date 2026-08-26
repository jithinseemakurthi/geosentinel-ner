"""
GeoSentinel-NER District Reference Registry

Single source of truth for representative North Eastern Region (NER)
locations used by data-ingestion, notification-service, and dev scripts.

NOTE: apps/web-dashboard/src/lib/districts.ts intentionally mirrors this
data for the frontend (TypeScript cannot import this Python module).
When adding a district here, update that file too.
"""
from typing import Dict, List

# District name -> representative coordinates (WGS84, [lat, lon]).
# Coordinates point at a well-known location within the district
# (HQ town where possible) and are only used for weather sampling.
DISTRICT_COORDS: Dict[str, Dict[str, float]] = {
    "Churachandpur": {"lat": 24.2, "lon": 93.68},
    "Aizawl": {"lat": 23.7271, "lon": 92.7176},
    "Gangtok": {"lat": 27.3389, "lon": 88.6065},
    "Shillong": {"lat": 25.5788, "lon": 91.8933},
    "Imphal West": {"lat": 24.817, "lon": 93.9368},
    "Imphal": {"lat": 24.817, "lon": 93.9368},
    "East Khasi Hills": {"lat": 25.46, "lon": 91.36},
    "Kohima": {"lat": 25.6751, "lon": 94.1086},
    "Itanagar": {"lat": 27.0844, "lon": 93.6053},
    "Dispur": {"lat": 26.1433, "lon": 91.7898},
    "Agartala": {"lat": 23.8315, "lon": 91.2868},
}

NORTHEAST_STATES: List[str] = [
    "Arunachal Pradesh",
    "Assam",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Sikkim",
    "Tripura",
]

# A single representative district per state (SMS digests must stay compact).
NORTHEAST_STATE_LOCATIONS: Dict[str, str] = {
    "Arunachal Pradesh": "Itanagar",
    "Assam": "Dispur",
    "Manipur": "Imphal",
    "Meghalaya": "Shillong",
    "Mizoram": "Aizawl",
    "Nagaland": "Kohima",
    "Sikkim": "Gangtok",
    "Tripura": "Agartala",
}

NORTHEAST_ABBREVIATIONS: Dict[str, str] = {
    "Arunachal Pradesh": "AR",
    "Assam": "AS",
    "Manipur": "MN",
    "Meghalaya": "ML",
    "Mizoram": "MZ",
    "Nagaland": "NL",
    "Sikkim": "SK",
    "Tripura": "TR",
}
