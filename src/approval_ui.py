#!/usr/bin/env python3
"""
Simple approval UI for submitting a flight request.

This uses the existing waypoint engine and deconfliction logic to provide a
basic approval decision for a requested origin/destination pair.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from waypoint_engine import generate_waypoints
from conflict_agent import build_conflict_report, interpret_conflict
from conflict_detector import detect_conflicts, load_volumes
from volumizer import Volume4D, build_volumes, save_geojson, visualize_volumes
from kml_exporter import build_kml


HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Flight Approval UI</title>
  <style>
    :root {{
      color-scheme: light;
      --sage: #7a8b5a;
      --earth: #8b5e3c;
      --clay: #c98a5f;
      --cream: #f7efe4;
      --moss: #47563b;
      --ink: #2f2a24;
    }}
    body {{
      font-family: "Trebuchet MS", "Segoe UI", "Gill Sans", Arial, sans-serif;
      margin: 2rem auto;
      max-width: 760px;
      background: linear-gradient(135deg, var(--cream), #efe0c7);
      color: var(--ink);
      padding: 1.5rem;
      border-radius: 16px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.08);
    }}
    h1 {{ color: var(--moss); margin-bottom: 0.5rem; }}
    form {{ display: grid; gap: 0.75rem; }}
    label {{ font-weight: 600; color: var(--earth); }}
    input, button {{
      padding: 0.7rem 0.8rem;
      font-size: 1rem;
      border-radius: 8px;
      border: 1px solid #cdb79e;
      background: #fffdf9;
    }}
    button {{
      background: linear-gradient(135deg, var(--earth), var(--clay));
      color: white;
      border: none;
      cursor: pointer;
      font-weight: 600;
    }}
    .result {{
      margin-top: 1.5rem;
      padding: 1rem;
      border: 1px solid #d8c3a4;
      border-radius: 10px;
      background: rgba(255,255,255,0.7);
    }}
    .approved {{ border-color: #4f6b3f; background: #eef6e8; }}
    .needs-review {{ border-color: #b46a2d; background: #fff3e2; }}
    .denied {{ border-color: #8b3e2f; background: #fbe9e6; }}
  </style>
</head>
<body>
  <h1>Flight Approval Request</h1>
  <form method="get">
    <label>Origin (lat,lon or place name)</label>
    <input name="origin" value="{origin_value}" required>
    <label>Destination (lat,lon or place name)</label>
    <input name="destination" value="{destination_value}" required>
    <label>Altitude (ft)</label>
    <input name="altitude" value="{altitude_value}" type="number">
    <button type="submit">Submit</button>
  </form>
  {result_section}
</body>
</html>
"""


class ApprovalHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path != "/":
            self.send_error(404)
            return

        origin = query.get("origin", [""])[0]
        destination = query.get("destination", [""])[0]
        altitude = float(query.get("altitude", [300])[0])

        if not origin or not destination:
            self._send_html(self._render_page(origin, destination, altitude, ""))
            return

        try:
            origin_lat, origin_lon = self._resolve_location(origin)
            dest_lat, dest_lon = self._resolve_location(destination)
            result = generate_waypoints(
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                dest_lat=dest_lat,
                dest_lon=dest_lon,
                altitude_ft=altitude,
            )
        except Exception as exc:  # pragma: no cover - UI path
            self._send_html(self._render_result(
                "denied",
                f"Request failed: {exc}",
                result=None,
                waypoint_path=None,
                volumes_path=None,
                origin_value=origin,
                destination_value=destination,
                altitude_value=altitude,
            ))
            return

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = ROOT / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        waypoint_path = out_dir / f"waypoints_ui_{ts}.json"
        with open(waypoint_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        try:
            volumes = build_volumes(result["waypoints"])
            volumes_path = out_dir / f"volumes_ui_{ts}.geojson"
            save_geojson(volumes, volumes_path)
            visualize_volumes(volumes, result["waypoints"], result.get("metadata"), volumes_path.with_suffix(".html"))
        except Exception as exc:  # pragma: no cover - UI path
            response_html = self._render_result(
                "denied",
                f"Could not generate flight volumes: {exc}",
                result,
                waypoint_path,
                None,
                origin_value=origin,
                destination_value=destination,
                altitude_value=altitude,
            )
            self._send_html(response_html)
            return

        conflicts = self._find_conflicts_against_existing(volumes, volumes_path)
        if conflicts:
            approval = "needs-review"
            reason = f"{len(conflicts)} conflict(s) detected with existing flight volumes."
        else:
            approval = "approved"
            reason = "No conflicts detected with existing flight volumes."

        response_html = self._render_result(
            approval,
            reason,
            result,
            waypoint_path,
            volumes_path,
            origin_value=origin,
            destination_value=destination,
            altitude_value=altitude,
        )
        self._send_html(response_html)

    @staticmethod
    def _resolve_location(value: str) -> tuple[float, float]:
        coord_match = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)\s*$", value)
        if coord_match:
            return float(coord_match.group(1)), float(coord_match.group(2))

        candidates = [value.strip()]
        if re.search(r"\bin\b", value, re.I):
            candidates.append(re.sub(r"\s+in\s+", " ", value, flags=re.I).strip())
            candidates.append(re.sub(r"\s+in\s+", ", ", value, flags=re.I).strip())
        candidates.append(re.sub(r"\bweekened\b", "weekend", value, flags=re.I).strip())

        for query in dict.fromkeys(candidates):
            coords = ApprovalHandler._geocode_place(query)
            if coords is not None:
                return coords

        raise ValueError(f"Could not resolve location: {value}")

    @staticmethod
    def _geocode_place(query: str) -> tuple[float, float] | None:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": query, "format": "jsonv2", "limit": 1}
        headers = {"User-Agent": "UTM-orchestrator/1.0"}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data:
            return None
        first = data[0]
        return float(first["lat"]), float(first["lon"])

    def _find_conflicts_against_existing(self, volumes: list[Volume4D], volumes_path: Path) -> list[dict]:
        existing_paths = sorted((ROOT / "output").glob("*.geojson"))
        conflicts = []
        for path in existing_paths:
            if path == volumes_path:
                continue
            try:
                other = load_volumes(path)
            except Exception:
                continue
            conflicts.extend(detect_conflicts(volumes, other, id_a="requested", id_b=path.stem))
        return conflicts

    def _render_page(self, origin_value: str = "", destination_value: str = "", altitude_value: int = 300, result_section: str = "") -> str:
        return HTML_TEMPLATE.format(
            origin_value=origin_value,
            destination_value=destination_value,
            altitude_value=altitude_value,
            result_section=result_section,
        )

    def _render_result(self, status: str, reason: str, result=None, waypoint_path=None, volumes_path=None, origin_value="", destination_value="", altitude_value=300) -> str:
        body = f"""
        <div class="result {status}">
          <h2>Decision: {status.upper()}</h2>
          <p>{reason}</p>
        """
        if origin_value and destination_value and status == "approved":
            body += f"<p><strong>Origin:</strong> {origin_value}</p>"
            body += f"<p><strong>Destination:</strong> {destination_value}</p>"
        if result:
            body += f"<p>Waypoints: {result['metadata']['waypoint_count']}</p>"
            body += f"<p>Distance: {result['metadata']['total_distance_m']} m</p>"
            body += f"<p>Duration: {result['metadata']['estimated_duration_s']/60:.1f} min</p>"
        if waypoint_path:
            body += f"<p>Waypoints file: <code>{waypoint_path.relative_to(ROOT)}</code></p>"
        if volumes_path:
            body += f"<p>Volumes file: <code>{volumes_path.relative_to(ROOT)}</code></p>"
        body += "</div>"
        return HTML_TEMPLATE.format(
            origin_value=origin_value,
            destination_value=destination_value,
            altitude_value=altitude_value,
            result_section=body,
        )

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the flight approval UI server.")
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the approval UI server",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    try:
        server = HTTPServer(("127.0.0.1", args.port), ApprovalHandler)
    except OSError as exc:
        print(f"Error: could not bind to port {args.port}: {exc}")
        print("Try a different port with --port, for example: python3 src/approval_ui.py --port 8001")
        raise SystemExit(1)

    print(f"Open http://127.0.0.1:{args.port}/ to use the approval UI")
    server.serve_forever()


if __name__ == "__main__":
    main()
