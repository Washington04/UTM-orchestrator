#!/usr/bin/env python3
"""
Volumizer: Build 4D operational intent volumes from a waypoint path.

For each consecutive waypoint pair one segment volume is created:
  - Horizontal footprint: LineString buffered in UTM (metric-accurate)
  - Altitude band:        waypoint alt_agl +/- vertical margin (feet)
  - Time window:          [t_i, t_{i+1}] from waypoint timestamps

Usage:
    python src/volumizer.py --waypoints output/waypoints.json
    python src/volumizer.py --waypoints output/waypoints.json \
        --buffer 50 --v-margin 20 --output output/volumes.geojson
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import folium
import geopandas as gpd
from shapely.geometry import LineString, Point, mapping, shape

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

CRS_WGS84 = "EPSG:4326"
CRS_METERS = "EPSG:26910"  # Seattle UTM Zone 10N

AOI_FILE = ROOT / "data" / "airspace" / "processed" / "queen_anne_aoi.geojson"
OBSTACLE_FILE = ROOT / "data" / "obstacles" / "faa_dof_queen_anne.geojson"


# ── Data model ────────────────────────────────────────────────────────────────

class Volume4D:
    def __init__(
        self,
        segment_index,        # int for segments, None for origin/dest cylinders
        polygon,              # Shapely Polygon in WGS84
        min_alt_ft: float,
        max_alt_ft: float,
        start_time: datetime,
        end_time: datetime,
        volume_type: str = "segment",   # "segment" | "origin" | "destination"
    ):
        self.segment_index = segment_index
        self.polygon = polygon
        self.min_alt_ft = min_alt_ft
        self.max_alt_ft = max_alt_ft
        self.start_time = start_time
        self.end_time = end_time
        self.volume_type = volume_type

    @classmethod
    def from_feature(cls, feature: Dict) -> "Volume4D":
        p = feature["properties"]
        return cls(
            segment_index=p.get("segment_index"),
            polygon=shape(feature["geometry"]),
            min_alt_ft=p["min_alt_ft"],
            max_alt_ft=p["max_alt_ft"],
            start_time=_parse_time(p["start_time"]),
            end_time=_parse_time(p["end_time"]),
            volume_type=p.get("volume_type", "segment"),
        )

    @property
    def duration_s(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    def overlaps(self, other: "Volume4D") -> bool:
        spatial = self.polygon.intersects(other.polygon)
        temporal = self.start_time < other.end_time and other.start_time < self.end_time
        vertical = self.min_alt_ft < other.max_alt_ft and other.min_alt_ft < self.max_alt_ft
        return spatial and temporal and vertical

    def to_feature(self) -> Dict:
        return {
            "type": "Feature",
            "geometry": mapping(self.polygon),
            "properties": {
                "volume_type": self.volume_type,
                "segment_index": self.segment_index,
                "min_alt_ft": round(self.min_alt_ft, 1),
                "max_alt_ft": round(self.max_alt_ft, 1),
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat(),
                "duration_s": round(self.duration_s, 1),
            },
        }


# ── Core builder ─────────────────────────────────────────────────────────────

def _make_cylinder_wgs(lat: float, lon: float, radius_m: float):
    """Return a circular Shapely Polygon (WGS84) with UTM-accurate radius."""
    gdf = gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs=CRS_WGS84)
    gdf_utm = gdf.to_crs(CRS_METERS)
    gdf_utm["geometry"] = gdf_utm.geometry.buffer(radius_m, resolution=8)
    return gdf_utm.to_crs(CRS_WGS84).geometry.iloc[0]


def _extend_line(line, extend_m: float):
    """Extend a UTM LineString by extend_m past each endpoint."""
    import math
    coords = list(line.coords)
    def _push(tip, anchor):
        dx, dy = tip[0] - anchor[0], tip[1] - anchor[1]
        d = math.hypot(dx, dy)
        if d == 0:
            return tip
        return (tip[0] + dx / d * extend_m, tip[1] + dy / d * extend_m)
    coords[0]  = _push(coords[0],  coords[1])
    coords[-1] = _push(coords[-1], coords[-2])
    return LineString(coords)


def build_volumes(
    waypoints: List[Dict],
    buffer_m: float = 5.0,
    v_margin_ft: float = 20.0,
    time_buffer_s: float = 0.25,
    cylinder_radius_m: float = 5.0,
) -> List[Volume4D]:
    """
    Create 4D volumes for an origin-to-destination flight path.

    Returns a list ordered as:
      [origin_cylinder, segment_0, ..., segment_N-2, destination_cylinder]

    Origin and destination cylinders span 0 ft AGL to cruise altitude with a
    5 m radius, representing the takeoff and landing envelopes. Segment volumes
    are UTM-buffered corridor rectangles at cruise altitude ± v_margin_ft.
    """
    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints to build volumes.")

    volumes: List[Volume4D] = []

    # ── Origin cylinder ───────────────────────────────────────────────────────
    wp_orig = waypoints[0]
    t_orig_raw = _parse_time(wp_orig["time"])
    t_next_raw = _parse_time(waypoints[1]["time"])
    volumes.append(Volume4D(
        segment_index=None,
        polygon=_make_cylinder_wgs(wp_orig["lat"], wp_orig["lon"], cylinder_radius_m),
        min_alt_ft=0.0,
        max_alt_ft=wp_orig["alt_agl"],
        start_time=t_orig_raw - timedelta(seconds=time_buffer_s),
        end_time=t_next_raw + timedelta(seconds=time_buffer_s),
        volume_type="origin",
    ))

    for i in range(len(waypoints) - 1):
        wp_a = waypoints[i]
        wp_b = waypoints[i + 1]

        t_start_raw = _parse_time(wp_a["time"])
        t_end_raw   = _parse_time(wp_b["time"])
        t_start = t_start_raw - timedelta(seconds=time_buffer_s)
        t_end   = t_end_raw   + timedelta(seconds=time_buffer_s)

        # Altitude band: span both endpoints, then add vertical margin
        alt_lo = min(wp_a["alt_agl"], wp_b["alt_agl"])
        alt_hi = max(wp_a["alt_agl"], wp_b["alt_agl"])
        min_alt = max(0.0, alt_lo - v_margin_ft)
        max_alt = alt_hi + v_margin_ft

        # Compute spatial extension = time_buffer × speed so the footprint
        # extends past each waypoint and adjacent volumes overlap spatially.
        seg_dist = wp_b["cumulative_distance_m"] - wp_a["cumulative_distance_m"]
        seg_dur  = (t_end_raw - t_start_raw).total_seconds()
        speed_mps = seg_dist / seg_dur if seg_dur > 0 else 0.0
        spatial_ext_m = time_buffer_s * speed_mps

        # Build segment line in WGS84, project to UTM, extend ends, buffer, reproject
        line_wgs = LineString([
            (wp_a["lon"], wp_a["lat"]),
            (wp_b["lon"], wp_b["lat"]),
        ])
        gdf = gpd.GeoDataFrame(geometry=[line_wgs], crs=CRS_WGS84)
        gdf_utm = gdf.to_crs(CRS_METERS)
        if spatial_ext_m > 0:
            gdf_utm["geometry"] = gdf_utm.geometry.apply(
                lambda g: _extend_line(g, spatial_ext_m)
            )
        gdf_utm["geometry"] = gdf_utm.geometry.buffer(buffer_m, cap_style=2)
        footprint_wgs = gdf_utm.to_crs(CRS_WGS84).geometry.iloc[0]

        volumes.append(Volume4D(
            segment_index=i,
            polygon=footprint_wgs,
            min_alt_ft=min_alt,
            max_alt_ft=max_alt,
            start_time=t_start,
            end_time=t_end,
            volume_type="segment",
        ))

    # ── Destination cylinder ──────────────────────────────────────────────────
    wp_dest = waypoints[-1]
    t_prev_raw = _parse_time(waypoints[-2]["time"])
    t_dest_raw = _parse_time(wp_dest["time"])
    volumes.append(Volume4D(
        segment_index=None,
        polygon=_make_cylinder_wgs(wp_dest["lat"], wp_dest["lon"], cylinder_radius_m),
        min_alt_ft=0.0,
        max_alt_ft=wp_dest["alt_agl"],
        start_time=t_prev_raw - timedelta(seconds=time_buffer_s),
        end_time=t_dest_raw + timedelta(seconds=time_buffer_s),
        volume_type="destination",
    ))

    return volumes


def detect_overlaps(volumes: List[Volume4D]) -> List[Tuple[int, int]]:
    """Return (i, j) pairs where same-flight volumes share 4D space (expected at boundaries)."""
    overlaps = []
    for i in range(len(volumes)):
        for j in range(i + 1, len(volumes)):
            if volumes[i].overlaps(volumes[j]):
                overlaps.append((i, j))
    return overlaps


# ── I/O ───────────────────────────────────────────────────────────────────────

def save_geojson(volumes: List[Volume4D], output_path: Path) -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [v.to_feature() for v in volumes],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(fc, f, indent=2)
    print(f"Volumes:  {output_path}")


def load_waypoints(path: Path) -> Tuple[List[Dict], Optional[Dict]]:
    """Load waypoints JSON produced by waypoint_engine. Returns (waypoints, metadata)."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data, None
    return data["waypoints"], data.get("metadata")


# ── Visualization ─────────────────────────────────────────────────────────────

def visualize_volumes(
    volumes: List[Volume4D],
    waypoints: List[Dict],
    metadata: Optional[Dict],
    output_path: Path,
) -> Path:
    """Build a Folium map showing volume footprints and the waypoint path."""
    lats = [w["lat"] for w in waypoints]
    lons = [w["lon"] for w in waypoints]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)]

    m = folium.Map(location=center, zoom_start=16, tiles=None)

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
        overlay=False,
        control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="CartoDB positron",
        name="Street Map",
        overlay=False,
        control=True,
        show=False,
    ).add_to(m)

    # AOI boundary
    if AOI_FILE.exists():
        aoi = gpd.read_file(AOI_FILE)
        if aoi.crs is None:
            aoi = aoi.set_crs(CRS_WGS84)
        folium.GeoJson(
            aoi,
            name="AOI",
            style_function=lambda _: {"color": "cyan", "weight": 2, "fill": False},
        ).add_to(m)

    # Obstacles
    if OBSTACLE_FILE.exists():
        obs = gpd.read_file(OBSTACLE_FILE)
        if obs.crs is None:
            obs = obs.set_crs(CRS_WGS84)
        obs_grp = folium.FeatureGroup(name="Obstacles", show=True)
        folium.GeoJson(
            obs,
            style_function=lambda _: {
                "color": "red", "weight": 1,
                "fill": True, "fillOpacity": 0.4, "fillColor": "red",
            },
        ).add_to(obs_grp)
        obs_grp.add_to(m)

    # Volume footprints
    vol_grp = folium.FeatureGroup(name="Volume footprints", show=True)
    _style = {
        "origin":      ("#00aaff", "#00aaff"),
        "destination": ("#00aaff", "#00aaff"),
        "segment":     ("#00aaff", "#00aaff"),
    }
    for v in volumes:
        coords = [[lat, lon] for lon, lat in v.polygon.exterior.coords]
        if v.volume_type == "origin":
            label = "Origin cylinder"
        elif v.volume_type == "destination":
            label = "Destination cylinder"
        else:
            label = f"Segment {v.segment_index}"
        tooltip_html = (
            f"<b>{label}</b><br>"
            f"Alt: {v.min_alt_ft:.0f} – {v.max_alt_ft:.0f} ft AGL<br>"
            f"Start: {v.start_time.strftime('%H:%M:%S')} UTC<br>"
            f"End:&nbsp;&nbsp; {v.end_time.strftime('%H:%M:%S')} UTC<br>"
            f"Duration: {v.duration_s:.1f} s"
        )
        color, fill_color = _style.get(v.volume_type, ("#00aaff", "#00aaff"))
        folium.Polygon(
            locations=coords,
            color=color,
            weight=1,
            fill=True,
            fill_color=fill_color,
            fill_opacity=0.35,
            tooltip=folium.Tooltip(tooltip_html, sticky=False),
        ).add_to(vol_grp)
    vol_grp.add_to(m)

    # Waypoint path overlay
    path_grp = folium.FeatureGroup(name="Waypoints", show=True)
    folium.PolyLine(
        [[w["lat"], w["lon"]] for w in waypoints],
        color="#00ff88", weight=3, opacity=0.9,
    ).add_to(path_grp)
    for w in waypoints:
        is_origin = w["step"] == 0
        is_dest   = w["step"] == len(waypoints) - 1
        label = "Origin" if is_origin else "Dest" if is_dest else f"Step {w['step']}"
        tip = (
            f"<b>{label}</b><br>"
            f"{w['lat']}, {w['lon']}<br>"
            f"Alt: {w['alt_agl']} ft AGL<br>"
            f"Time: {w['time']}"
        )
        if is_origin:
            folium.Marker(
                [w["lat"], w["lon"]],
                tooltip=folium.Tooltip(tip, sticky=False),
                icon=folium.Icon(color="green", icon="circle", prefix="fa"),
            ).add_to(path_grp)
        elif is_dest:
            folium.Marker(
                [w["lat"], w["lon"]],
                tooltip=folium.Tooltip(tip, sticky=False),
                icon=folium.Icon(color="red", icon="flag", prefix="fa"),
            ).add_to(path_grp)
        else:
            folium.CircleMarker(
                [w["lat"], w["lon"]],
                radius=4, color="white", weight=1,
                fill=True, fill_color="#00ff88", fill_opacity=1.0,
                tooltip=folium.Tooltip(tip, sticky=False),
            ).add_to(path_grp)
    path_grp.add_to(m)

    # Info panel
    meta = metadata or {}
    info_html = f"""
    <div style="position:fixed;top:12px;left:60px;z-index:1000;
                background:rgba(0,0,0,0.72);color:#fff;
                padding:10px 14px;border-radius:7px;
                font-family:monospace;font-size:13px;line-height:1.6;">
        <b>4D Volumes</b><br>
        Segments: {len(volumes)}<br>
        Buffer: {meta.get('buffer_m', '—')} m horizontal<br>
        V-margin: {meta.get('v_margin_ft', '—')} ft vertical<br>
        Alt: {meta.get('altitude_ft', waypoints[0].get('alt_agl', '—'))} ft AGL<br>
        Distance: {meta.get('total_distance_m', '—')} m
    </div>
    """
    m.get_root().html.add_child(folium.Element(info_html))

    folium.LayerControl().add_to(m)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_path))
    return output_path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_time(value) -> datetime:
    if isinstance(value, datetime):
        return value
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build 4D operational intent volumes from a waypoint path.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--waypoints",
        required=True,
        metavar="PATH",
        help="Waypoints JSON produced by waypoint_engine.py",
    )
    parser.add_argument(
        "--buffer",
        type=float,
        default=5.0,
        metavar="M",
        help="Horizontal corridor half-width in meters",
    )
    parser.add_argument(
        "--v-margin",
        type=float,
        default=20.0,
        metavar="FT",
        help="Vertical margin above and below cruise altitude (feet)",
    )
    parser.add_argument(
        "--output",
        default="output/volumes.geojson",
        metavar="PATH",
        help="Output GeoJSON file (relative to repo root)",
    )
    args = parser.parse_args()

    wp_path = Path(args.waypoints)
    if not wp_path.is_absolute():
        wp_path = ROOT / wp_path

    waypoints, metadata = load_waypoints(wp_path)
    volumes = build_volumes(waypoints, buffer_m=args.buffer, v_margin_ft=args.v_margin)

    out_path = ROOT / args.output
    save_geojson(volumes, out_path)

    map_path = out_path.with_suffix(".html")
    if metadata:
        metadata["buffer_m"] = args.buffer
        metadata["v_margin_ft"] = args.v_margin
    visualize_volumes(volumes, waypoints, metadata, map_path)

    overlaps = detect_overlaps(volumes)

    print(f"Volumes:  {len(volumes)}")
    print(f"Overlaps: {len(overlaps)}" + (f" — indices {overlaps}" if overlaps else " (none)"))
    print(f"Map:      {map_path.as_uri()}")
