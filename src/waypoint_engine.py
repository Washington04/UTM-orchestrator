#!/usr/bin/env python3
"""
Waypoint Engine: Convert origin/destination lat-lon into a 4D waypoint path.

Takes decimal-degree coordinates, snaps them to the obstacle-aware grid,
runs A* to find the optimal route, then emits a timestamped waypoint list
that the volumizer can consume directly.

Usage:
    python src/waypoint_engine.py --origin 47.6336,-122.3572 --dest 47.6311,-122.3503
    python src/waypoint_engine.py --origin 47.6336,-122.3572 --dest 47.6311,-122.3503 \
        --altitude-ft 300 --speed 27 --output output/waypoints.json
"""

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import folium
import geopandas as gpd

# Resolve repo root so this script works from any cwd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from neighborhood_graph import (
    AOI_FILE,
    OBSTACLE_FILE,
    SPACING_M,
    astar,
    build_nodes,
    load_aoi_m,
    load_obstacles_m,
    mask_blocked,
    snap_latlon_to_node,
    to_latlon,
)

OUTPUT_DIR = ROOT / "output"

# Snapping distance beyond which we warn the caller (meters)
SNAP_WARN_THRESHOLD_M = 150.0


def _euclidean_m(a, b) -> float:
    """Distance in meters between two Shapely Points in UTM."""
    return math.hypot(b.x - a.x, b.y - a.y)


def _snap_distance_m(lat: float, lon: float, snapped_point) -> float:
    """
    Approximate great-circle distance (meters) between a requested lat-lon
    and its snapped UTM point. Used only for the user-facing warning.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    req_gdf = gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs="EPSG:4326").to_crs("EPSG:26910")
    req_pt = req_gdf.geometry.iloc[0]
    return math.hypot(snapped_point.x - req_pt.x, snapped_point.y - req_pt.y)


def generate_waypoints(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    altitude_ft: float = 300.0,
    cruise_speed_mps: float = 27.0,
    departure_time: Optional[datetime] = None,
) -> Dict:
    """
    Generate a timestamped waypoint path from origin to destination.

    Args:
        origin_lat/lon: Departure point in decimal degrees (WGS84).
        dest_lat/lon:   Arrival point in decimal degrees (WGS84).
        altitude_ft:    Constant cruise altitude above ground level (feet).
        cruise_speed_mps: Constant cruise speed (meters per second).
        departure_time: Mission start time (UTC). Defaults to now.

    Returns:
        Dict with 'metadata' and 'waypoints' keys. 'waypoints' is a list of
        {lat, lon, alt_agl, time, step, cumulative_distance_m} dicts, ordered
        origin → destination, compatible with volumizer.create_volumes_from_path().

    Raises:
        RuntimeError: If no obstacle-free path exists between the two points.
    """
    if departure_time is None:
        departure_time = datetime.now(timezone.utc)

    # ── Build obstacle-aware grid ──────────────────────────────────────────
    aoi_m = load_aoi_m().iloc[0]
    obs_m = load_obstacles_m()

    nodes_gdf = build_nodes(aoi_m, SPACING_M)
    valid, _ = mask_blocked(nodes_gdf, obs_m)

    nodes_xy = {
        (int(r), int(c)): geom
        for r, c, geom in zip(nodes_gdf["r"], nodes_gdf["c"], nodes_gdf.geometry)
    }

    # ── Snap origin and destination to nearest valid grid nodes ───────────
    origin_node = snap_latlon_to_node(origin_lat, origin_lon, nodes_xy, valid)
    dest_node   = snap_latlon_to_node(dest_lat,   dest_lon,   nodes_xy, valid)

    origin_pt = nodes_xy[origin_node]
    dest_pt   = nodes_xy[dest_node]

    origin_snap_dist = _snap_distance_m(origin_lat, origin_lon, origin_pt)
    dest_snap_dist   = _snap_distance_m(dest_lat,   dest_lon,   dest_pt)

    if origin_snap_dist > SNAP_WARN_THRESHOLD_M:
        print(
            f"[warn] Origin snapped {origin_snap_dist:.0f} m from requested point. "
            "It may lie outside the AOI or obstacle buffer.",
            file=sys.stderr,
        )
    if dest_snap_dist > SNAP_WARN_THRESHOLD_M:
        print(
            f"[warn] Destination snapped {dest_snap_dist:.0f} m from requested point. "
            "It may lie outside the AOI or obstacle buffer.",
            file=sys.stderr,
        )

    # ── A* pathfinding ────────────────────────────────────────────────────
    path_nodes = astar(origin_node, dest_node, valid)
    if path_nodes is None:
        raise RuntimeError(
            f"No obstacle-free path found from ({origin_lat}, {origin_lon}) "
            f"to ({dest_lat}, {dest_lon}). Both points may be in blocked areas."
        )

    # ── Convert grid nodes → UTM Points → lat-lon ─────────────────────────
    path_points_m: List = [nodes_xy[n] for n in path_nodes]
    path_latlon: List[Tuple[float, float]] = to_latlon(path_points_m)

    # ── Compute cumulative distance along the path (UTM meters) ───────────
    cumulative: List[float] = [0.0]
    for i in range(1, len(path_points_m)):
        seg_dist = _euclidean_m(path_points_m[i - 1], path_points_m[i])
        cumulative.append(cumulative[-1] + seg_dist)

    total_distance_m = cumulative[-1]
    total_duration_s = total_distance_m / cruise_speed_mps if cruise_speed_mps > 0 else 0.0

    # ── Build waypoint list ───────────────────────────────────────────────
    waypoints: List[Dict] = []
    for i, ((lat, lon), dist_m) in enumerate(zip(path_latlon, cumulative)):
        elapsed = timedelta(seconds=dist_m / cruise_speed_mps) if cruise_speed_mps > 0 else timedelta(0)
        waypoints.append(
            {
                "lat": round(lat, 7),
                "lon": round(lon, 7),
                "alt_agl": altitude_ft,
                "time": (departure_time + elapsed).isoformat(),
                "step": i,
                "cumulative_distance_m": round(dist_m, 1),
            }
        )

    origin_ll  = path_latlon[0]
    dest_ll    = path_latlon[-1]

    return {
        "metadata": {
            "origin_requested":    {"lat": origin_lat, "lon": origin_lon},
            "destination_requested": {"lat": dest_lat, "lon": dest_lon},
            "origin_snapped":      {"lat": round(origin_ll[0], 7),  "lon": round(origin_ll[1], 7)},
            "destination_snapped": {"lat": round(dest_ll[0], 7),    "lon": round(dest_ll[1], 7)},
            "origin_snap_dist_m":  round(origin_snap_dist, 1),
            "dest_snap_dist_m":    round(dest_snap_dist, 1),
            "altitude_ft":         altitude_ft,
            "cruise_speed_mps":    cruise_speed_mps,
            "departure_time":      departure_time.isoformat(),
            "total_distance_m":    round(total_distance_m, 1),
            "estimated_duration_s": round(total_duration_s, 1),
            "waypoint_count":      len(waypoints),
            "grid_spacing_m":      SPACING_M,
        },
        "waypoints": waypoints,
    }


def visualize_waypoints(result: Dict, output_path: Path) -> Path:
    """
    Build a Folium map showing the AOI, obstacles, and A* waypoint path.
    Returns the path to the saved HTML file.
    """
    waypoints = result["waypoints"]
    meta = result["metadata"]

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
    aoi_wgs = gpd.read_file(AOI_FILE)
    if aoi_wgs.crs is None:
        aoi_wgs = aoi_wgs.set_crs("EPSG:4326")
    folium.GeoJson(
        aoi_wgs,
        name="AOI",
        style_function=lambda _: {"color": "cyan", "weight": 2, "fill": False},
    ).add_to(m)

    # Obstacles
    if OBSTACLE_FILE.exists():
        obs = gpd.read_file(OBSTACLE_FILE)
        if obs.crs is None:
            obs = obs.set_crs("EPSG:4326")
        obs_group = folium.FeatureGroup(name="Obstacles", show=True)
        folium.GeoJson(
            obs,
            style_function=lambda _: {
                "color": "red",
                "weight": 1,
                "fill": True,
                "fillOpacity": 0.5,
                "fillColor": "red",
            },
        ).add_to(obs_group)
        obs_group.add_to(m)

    # Route polyline
    path_coords = [[w["lat"], w["lon"]] for w in waypoints]
    folium.PolyLine(
        path_coords,
        color="#00ff88",
        weight=4,
        opacity=0.9,
        tooltip="A* route",
    ).add_to(m)

    # Waypoint markers
    wp_group = folium.FeatureGroup(name="Waypoints", show=True)
    for w in waypoints:
        is_origin = w["step"] == 0
        is_dest = w["step"] == len(waypoints) - 1
        tooltip_html = (
            f"<b>Step {w['step']}</b><br>"
            f"Lat: {w['lat']}<br>"
            f"Lon: {w['lon']}<br>"
            f"Alt: {w['alt_agl']} ft AGL<br>"
            f"Time: {w['time']}<br>"
            f"Dist: {w['cumulative_distance_m']} m"
        )
        if is_origin:
            folium.Marker(
                location=[w["lat"], w["lon"]],
                tooltip=folium.Tooltip(f"<b>Origin</b><br>{tooltip_html}", sticky=False),
                icon=folium.Icon(color="green", icon="circle", prefix="fa"),
            ).add_to(wp_group)
        elif is_dest:
            folium.Marker(
                location=[w["lat"], w["lon"]],
                tooltip=folium.Tooltip(f"<b>Destination</b><br>{tooltip_html}", sticky=False),
                icon=folium.Icon(color="red", icon="flag", prefix="fa"),
            ).add_to(wp_group)
        else:
            folium.CircleMarker(
                location=[w["lat"], w["lon"]],
                radius=5,
                color="white",
                weight=1,
                fill=True,
                fill_color="#00ff88",
                fill_opacity=1.0,
                tooltip=folium.Tooltip(tooltip_html, sticky=False),
            ).add_to(wp_group)
    wp_group.add_to(m)

    # Info panel
    title_html = f"""
    <div style="position:fixed;top:12px;left:60px;z-index:1000;
                background:rgba(0,0,0,0.72);color:#fff;
                padding:10px 14px;border-radius:7px;
                font-family:monospace;font-size:13px;line-height:1.6;">
        <b>Waypoint Route</b><br>
        Waypoints: {meta['waypoint_count']}<br>
        Distance:&nbsp; {meta['total_distance_m']} m<br>
        Duration:&nbsp; {meta['estimated_duration_s']} s
                  ({meta['estimated_duration_s']/60:.1f} min)<br>
        Altitude:&nbsp; {meta['altitude_ft']} ft AGL<br>
        Speed:&nbsp;&nbsp;&nbsp; {meta['cruise_speed_mps']} m/s
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    folium.LayerControl().add_to(m)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_path))
    return output_path


def _parse_latlon(value: str, label: str) -> Tuple[float, float]:
    try:
        lat_s, lon_s = value.split(",")
        return float(lat_s.strip()), float(lon_s.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid {label} format '{value}'. Expected 'lat,lon' e.g. '47.6336,-122.3572'."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a 4D waypoint path between two lat-lon coordinates.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--origin",
        required=True,
        metavar="LAT,LON",
        help="Origin coordinate in decimal degrees, e.g. '47.6336,-122.3572'",
    )
    parser.add_argument(
        "--dest",
        required=True,
        metavar="LAT,LON",
        help="Destination coordinate in decimal degrees, e.g. '47.6311,-122.3503'",
    )
    parser.add_argument(
        "--altitude-ft",
        type=float,
        default=300.0,
        metavar="FT",
        help="Cruise altitude above ground level (feet)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=27.0,
        metavar="MPS",
        help="Cruise speed (meters per second)",
    )
    parser.add_argument(
        "--departure",
        metavar="ISO8601",
        help="Departure time in ISO 8601 format (default: now UTC)",
    )
    parser.add_argument(
        "--output",
        default="output/waypoints.json",
        metavar="PATH",
        help="Output JSON file path (relative to repo root)",
    )
    args = parser.parse_args()

    origin_lat, origin_lon = _parse_latlon(args.origin, "origin")
    dest_lat,   dest_lon   = _parse_latlon(args.dest,   "destination")

    departure: Optional[datetime] = None
    if args.departure:
        departure = datetime.fromisoformat(args.departure)
        if departure.tzinfo is None:
            departure = departure.replace(tzinfo=timezone.utc)

    result = generate_waypoints(
        origin_lat, origin_lon,
        dest_lat, dest_lon,
        altitude_ft=args.altitude_ft,
        cruise_speed_mps=args.speed,
        departure_time=departure,
    )

    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    # HTML map — same stem as the JSON, different suffix
    map_path = output_path.with_suffix(".html")
    visualize_waypoints(result, map_path)

    meta = result["metadata"]
    print(f"Waypoints:         {meta['waypoint_count']}")
    print(f"Total distance:    {meta['total_distance_m']} m")
    print(f"Estimated flight:  {meta['estimated_duration_s']} s  ({meta['estimated_duration_s']/60:.1f} min)")
    print(f"Origin snapped:    {meta['origin_snap_dist_m']} m from requested point")
    print(f"Dest snapped:      {meta['dest_snap_dist_m']} m from requested point")
    print(f"Data:              {output_path}")
    print(f"Map:               {map_path.as_uri()}")
