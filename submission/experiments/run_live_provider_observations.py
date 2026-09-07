from __future__ import annotations

import csv
import hashlib
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


OUTPUT_DIR = Path(__file__).resolve().parent
OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=19.0760&longitude=72.8777"
    "&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,"
    "wind_speed_10m,visibility&timezone=UTC"
)
NOAA_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
REPETITIONS = 5


def percentile(values: list[float], value: float) -> float:
    ordered = sorted(values)
    return ordered[int(round((len(ordered) - 1) * value))]


def validate_open_meteo(payload: object) -> tuple[bool, str, str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("current"), dict):
        return False, "", "missing current object"
    current = payload["current"]
    required = {
        "time",
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "weather_code",
        "wind_speed_10m",
        "visibility",
    }
    missing = sorted(required - set(current))
    if missing:
        return False, str(current.get("time", "")), f"missing: {','.join(missing)}"
    return True, str(current["time"]), "required fields present"


def validate_noaa(payload: object) -> tuple[bool, str, str]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[-1], dict):
        return False, "", "missing latest object row"
    latest = payload[-1]
    timestamp = latest.get("time_tag")
    kp = latest.get("Kp")
    try:
        kp_value = float(kp)
    except (TypeError, ValueError):
        return False, str(timestamp or ""), "Kp is not numeric"
    if timestamp is None or not 0 <= kp_value <= 9:
        return False, str(timestamp or ""), "timestamp missing or Kp outside 0-9"
    return True, str(timestamp), f"Kp={kp_value:.2f}"


def main() -> None:
    rows: list[dict[str, object]] = []
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for repetition in range(1, REPETITIONS + 1):
            for provider, url, validator in (
                ("Open-Meteo", OPEN_METEO_URL, validate_open_meteo),
                ("NOAA SWPC", NOAA_URL, validate_noaa),
            ):
                started = time.perf_counter_ns()
                checked_at = datetime.now(timezone.utc)
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    valid, observed_at, detail = validator(response.json())
                    status_code = response.status_code
                    error = ""
                except Exception as exc:
                    valid, observed_at, detail = False, "", "provider request failed"
                    status_code = getattr(getattr(exc, "response", None), "status_code", 0)
                    error = type(exc).__name__
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                rows.append(
                    {
                        "repetition": repetition,
                        "provider": provider,
                        "checked_at_utc": checked_at.isoformat(),
                        "http_status": status_code,
                        "schema_valid": valid,
                        "observed_at_provider": observed_at,
                        "detail": detail,
                        "error_type": error,
                        "latency_ms": round(elapsed_ms, 3),
                    }
                )

    csv_path = OUTPUT_DIR / "live_provider_observations.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    aggregates = []
    for provider in ("Open-Meteo", "NOAA SWPC"):
        provider_rows = [row for row in rows if row["provider"] == provider]
        latencies = [float(row["latency_ms"]) for row in provider_rows]
        valid_count = sum(bool(row["schema_valid"]) for row in provider_rows)
        aggregates.append(
            {
                "provider": provider,
                "requests": len(provider_rows),
                "http_200": sum(int(row["http_status"]) == 200 for row in provider_rows),
                "schema_valid": valid_count,
                "availability_pct": round(valid_count * 100 / len(provider_rows), 2),
                "latency_ms_mean": round(statistics.fmean(latencies), 3),
                "latency_ms_p95": round(percentile(latencies, 0.95), 3),
            }
        )
    summary = {
        "experiment": "Public live-provider observation check",
        "executed_at_utc": rows[0]["checked_at_utc"],
        "location": "Mumbai, India (19.0760, 72.8777)",
        "total_requests": len(rows),
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "providers": aggregates,
        "limitations": [
            "This short observation window does not estimate long-term provider uptime.",
            "Railway and maritime enterprise feeds were not tested because credentials were unavailable.",
        ],
    }
    (OUTPUT_DIR / "live_provider_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
