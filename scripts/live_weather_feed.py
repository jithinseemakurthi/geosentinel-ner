"""
GeoSentinel live weather feed (development realtime bridge).

Polls the keyless Open-Meteo API for all monitored NER districts, converts
forecast + antecedent rainfall into M2-style risk scores (same heuristic as
ml-engine), and broadcasts alert events to every connected dashboard over the
gateway WebSocket. No database required.

Usage:  python scripts/live_weather_feed.py   (Ctrl+C to stop)
Requires: gateway running on :8000 with APP_DEBUG=true.
"""
import json
import math
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "geosentinel-shared"))

from geosentinel_shared.districts import DISTRICT_COORDS, NORTHEAST_STATE_LOCATIONS

GATEWAY = "http://127.0.0.1:8000/api/v1"
INTERVAL_S = 120

DISTRICTS = {
    district: DISTRICT_COORDS[district]
    for district in sorted(set(NORTHEAST_STATE_LOCATIONS.values()))
}

SEV_BY_SCORE = [(0.8, "evacuation"), (0.5, "warning"), (0.3, "watch")]


def score(f12: float, a3: float, a7: float) -> float:
    z = 0.9 * math.log1p(f12) + 0.6 * math.log1p(a3) + 0.3 * math.log1p(a7) - 3.2
    return max(0.02, min(0.97, 1 / (1 + math.exp(-z))))


def fetch(district: str) -> dict:
    c = DISTRICTS[district]
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={c['lat']}&longitude={c['lon']}"
        "&hourly=precipitation&past_hours=72&forecast_days=2&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "GeoSentinel-NER/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        h = json.loads(r.read())["hourly"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    times = [datetime.fromisoformat(t) for t in h["time"]]
    mm = [v or 0.0 for v in h["precipitation"]]
    # Next 12h accumulation: Open-Meteo hourly steps are instant values at
    # their timestamp, so take every step in [now, now+12h).
    f12 = sum(
        v for t, v in zip(times, mm)
        if 0 <= (t - now).total_seconds() < 43200
    )
    a3 = sum(v for t, v in zip(times, mm) if -259200 <= (t - now).total_seconds() < 0)
    a7 = sum(v for t, v in zip(times, mm) if -604800 <= (t - now).total_seconds() < 0)
    return {"f12": round(f12, 1), "a3": round(a3, 1), "a7": round(a7, 1)}


def severity(s: float) -> str:
    for floor, sev in SEV_BY_SCORE:
        if s >= floor:
            return sev
    return "advisory"


def broadcast(event: dict) -> int:
    req = urllib.request.Request(
        f"{GATEWAY}/dev/broadcast",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read())
            return out.get("clients", 0)
    except Exception as e:
        print(f"  ! broadcast failed: {e}")
        return -1


def cycle() -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] polling Open-Meteo for {len(DISTRICTS)} districts...")
    results = []
    for district in DISTRICTS:
        try:
            m = fetch(district)
            s = score(m["f12"], m["a3"], m["a7"])
            results.append((district, s, m))
            print(
                f"  {district:<16} next12h={m['f12']:>5}mm  3d={m['a3']:>6}mm"
                f"  7d={m['a7']:>6}mm  risk={s:.2f} ({severity(s)})"
            )
        except Exception as e:
            print(f"  {district:<16} FAILED {e}")

    if not results:
        return
    top_district, top_score, top_m = max(results, key=lambda r: r[1])
    event = {
        "type": "alert.new",
        "payload": {
            "id": f"live-{top_district.lower().replace(' ', '-')}",
            "severity": severity(top_score),
            "title": (
                f"{severity(top_score).upper()} · {top_district}: "
                f"{top_m['f12']}mm rain expected / {top_m['a7']}mm past week"
            ),
            "zone": "LIVE-OM",
            "district": top_district,
            "message": (
                f"Open-Meteo live feed: 12h forecast {top_m['f12']}mm, "
                f"antecedent 3d {top_m['a3']}mm / 7d {top_m['a7']}mm. "
                f"M2 heuristic risk {top_score:.2f}."
            ),
            "probability": round(top_score, 2),
            "issued_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    clients = broadcast(event)
    print(f"  -> broadcast '{severity(top_score)}' for {top_district} to {clients} client(s)")


if __name__ == "__main__":
    print("GeoSentinel live weather feed — Ctrl+C to stop")
    while True:
        try:
            cycle()
        except Exception as e:
            print(f"cycle error: {e}")
        time.sleep(INTERVAL_S)
