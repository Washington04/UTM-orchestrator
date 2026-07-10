#!/usr/bin/env python3
"""
Conflict Detector: Check for 4D volume conflicts between two or more flights.

A conflict occurs when volumes from *different* flights overlap in all three
dimensions simultaneously: horizontal footprint, altitude band, and time window.
Conflicting volumes are highlighted red in the output KML.

Usage:
    python src/conflict_detector.py \
        --flight output/volumes.geojson \
        --flight output/volumes_2.geojson \
        --flight output/volumes_3.geojson
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from volumizer import Volume4D
from kml_exporter import build_kml, build_combined_kml, _load_volumes, _load_waypoints
<<<<<<< HEAD
=======
from conflict_agent import build_conflict_report, interpret_conflict
>>>>>>> b815154 (Initial repository import and approval UI update)


def detect_conflicts(
    volumes_a: List[Volume4D],
    volumes_b: List[Volume4D],
    id_a: str = "flight_a",
    id_b: str = "flight_b",
) -> List[Dict]:
    """
    Compare every volume in flight A against every volume in flight B.
    Returns a list of conflict records for any 4D overlap found.
    """
    conflicts = []
    for i, va in enumerate(volumes_a):
        for j, vb in enumerate(volumes_b):
            if va.overlaps(vb):
                conflicts.append({
                    "flight_a":       id_a,
                    "flight_b":       id_b,
                    "volume_a_index": i,
                    "volume_b_index": j,
                    "volume_a_type":  va.volume_type,
                    "volume_b_type":  vb.volume_type,
                    "alt_a_ft":       f"{va.min_alt_ft:.0f}–{va.max_alt_ft:.0f}",
                    "alt_b_ft":       f"{vb.min_alt_ft:.0f}–{vb.max_alt_ft:.0f}",
                    "time_a_utc":     f"{va.start_time.strftime('%H:%M:%S')}–{va.end_time.strftime('%H:%M:%S')}",
                    "time_b_utc":     f"{vb.start_time.strftime('%H:%M:%S')}–{vb.end_time.strftime('%H:%M:%S')}",
                })
    return conflicts


def conflicting_indices_by_flight(all_conflicts: List[Dict]) -> Dict[str, Set[int]]:
    """Return {flight_id: {volume_indices}} for every flight that has a conflict."""
    result: Dict[str, Set[int]] = {}
    for c in all_conflicts:
        result.setdefault(c["flight_a"], set()).add(c["volume_a_index"])
        result.setdefault(c["flight_b"], set()).add(c["volume_b_index"])
    return result


def load_volumes(path: Path) -> List[Volume4D]:
    with open(path) as f:
        features = json.load(f)["features"]
    return [Volume4D.from_feature(feat) for feat in features]


def print_report(conflicts: List[Dict], id_a: str, id_b: str) -> None:
    if not conflicts:
        print(f"  No conflicts between {id_a} and {id_b}.")
        return
    print(f"  {len(conflicts)} conflict(s) between {id_a} and {id_b}:")
    for c in conflicts:
        print(
            f"    [{c['volume_a_type']:>12}] vol {c['volume_a_index']:>2}  ×  "
            f"[{c['volume_b_type']:>12}] vol {c['volume_b_index']:>2} | "
            f"alt {c['alt_a_ft']} ft  ×  {c['alt_b_ft']} ft | "
            f"time {c['time_a_utc']}  ×  {c['time_b_utc']} UTC"
        )


def _waypoints_path_for(volumes_path: Path) -> Path:
    """Derive the waypoints JSON path from a volumes GeoJSON path."""
    name = volumes_path.stem.replace("volumes", "waypoints")
    return volumes_path.parent / f"{name}.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Detect 4D conflicts between flights and export highlighted KMLs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--flight",
        action="append",
        required=True,
        metavar="PATH",
        help="Volumes GeoJSON for one flight (repeat for each flight)",
    )
    args = parser.parse_args()

    if len(args.flight) < 2:
        parser.error("Provide at least two --flight paths to compare.")

    paths        = [ROOT / p if not Path(p).is_absolute() else Path(p) for p in args.flight]
    flight_ids   = [p.stem for p in paths]
    raw_features = [_load_volumes(p) for p in paths]
    flight_vols  = [load_volumes(p) for p in paths]

    # ── Detect all cross-flight conflicts ─────────────────────────────────────
    print("\nConflict check:")
    all_conflicts: List[Dict] = []
    for i in range(len(flight_vols)):
        for j in range(i + 1, len(flight_vols)):
            conflicts = detect_conflicts(
                flight_vols[i], flight_vols[j],
                id_a=flight_ids[i], id_b=flight_ids[j],
            )
            print_report(conflicts, flight_ids[i], flight_ids[j])
            all_conflicts.extend(conflicts)

    print(f"\nTotal conflicts: {len(all_conflicts)}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    conflict_summaries = [interpret_conflict(c) for c in all_conflicts]
    report_text = build_conflict_report(
        conflict_summaries,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    report_path = out_dir / f"conflict_report_{ts}.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\nConflict report: {report_path.name}")

    # ── Export KML per flight with conflicting volumes highlighted red ─────────
    conflict_map = conflicting_indices_by_flight(all_conflicts)
    print("\nExporting KMLs:")
    flight_data = []
    for fid, features, vol_path in zip(flight_ids, raw_features, paths):
        wp_path   = _waypoints_path_for(vol_path)
        waypoints = _load_waypoints(wp_path) if wp_path.exists() else None
        conflicting = conflict_map.get(fid, set())

        xml_str  = build_kml(features, waypoints, conflicting_indices=conflicting)
        out_path = out_dir / f"{fid}_{ts}.kml"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(xml_str)

        status = f"{len(conflicting)} volume(s) highlighted red" if conflicting else "no conflicts"
        print(f"  {out_path.name}  —  {status}")

        flight_data.append({
            "id":                fid,
            "features":          features,
            "waypoints":         waypoints,
            "conflicting_indices": conflicting,
        })

    # ── Export single combined KML ────────────────────────────────────────────
    combined_xml  = build_combined_kml(flight_data)
    combined_path = out_dir / f"all_flights_{ts}.kml"
    with open(combined_path, "w", encoding="utf-8") as f:
        f.write(combined_xml)
    total_conflicting = sum(len(d["conflicting_indices"]) for d in flight_data)
    print(f"\nCombined KML: {combined_path.name}  —  {total_conflicting} total volume(s) highlighted red")
