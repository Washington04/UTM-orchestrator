from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone


from notam_fetch import NotamApiConfig, fetch_notams
from notam_constraints import extract_notam_constraints


def _write_fc(out_dir: Path, name: str, fc: Dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{name}.geojson"
    p.write_text(json.dumps(fc, indent=2))
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--icao", required=True, help="ICAO airport code (e.g. KSEA)")
    ap.add_argument("--out", default="outputs/notam_constraints", help="output dir under repo")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    cfg = NotamApiConfig(
        base_url=os.environ["NOTAM_BASE_URL"],
        auth_url=os.environ.get("NOTAM_AUTH_URL"),
    )

    params = {
    "location": args.icao,
    "limit": args.limit,
    }

    # 1) Fetch raw NOTAMs (returns GeoJSON FeatureCollection after your normalize step)
    data, meta = fetch_notams(
        config=cfg,
        notams_endpoint="/notams",
        params=params,
    )

    print("HTTP status:", meta.get("status_code"))

    features = data.get("features", [])
    print(f"NOTAM count: {len(features)}")
  
    def _notam_text(f):
        props = f.get("properties") or {}
        notam = ((props.get("coreNOTAMData") or {}).get("notam") or {})
        return notam.get("text") or ""

    for i, f in enumerate(features[:3], start=1):
        t = _notam_text(f)
        print(f"\n--- NOTAM {i} ---\n{t[:300]}")


# --- Milestone stop: raw NOTAM fetch only ---
    run_dir = Path(".notam_runs")
    run_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_out_path = run_dir / f"notams_{args.icao}_{ts}.json"
    raw_out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nWrote raw NOTAMs: {raw_out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
