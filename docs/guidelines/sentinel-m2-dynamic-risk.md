---
id: sentinel-m2
collection: geosentinel_guidelines
title: "GeoSentinel M2 — Dynamic Risk"
source: GeoSentinel
year: 2024
---

M2 heuristic: 0.45·f12 + 0.35·a3/100 + 0.20·a7/200 clipped 0–1. f12 is Open-Meteo next-12h forecast (mm), a3/a7 are 3-day/7-day antecedent rainfall (mm). Thresholds: advisory <0.30 < watch <0.50 < warning <0.75 < evacuation. Data source is Open-Meteo (keyless) via data-ingestion /weather/current/{district}. Forecast model is GFS/ECMWF blend; a3/a7 computed from TimescaleDB sensor_reading + Open-Meteo archive.
