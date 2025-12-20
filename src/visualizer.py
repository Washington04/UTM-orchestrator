#!/usr/bin/env python3
"""
Visualize flight routes from generated flights JSON on a Leaflet/Folium map.

Usage (from repo root):

  python src/visualize_routes.py
  python src/visualize_routes.py --flights output/flights_20251119_153045.json

Outputs an HTML map:

  output/flights_map_YYYYMMDD_HHMMSS.html
"""

import argparse
import json
import glob
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import geopandas as gpd
import folium

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---- Paths based on your repo layout ----

SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent

OUTPUT_DIR = ROOT_DIR / "output"
DATA_DIR = ROOT_DIR / "data"
OBSTACLE_FILE = DATA_DIR / "obstacles" / "faa_dof_seattle.geojson"
CITY_LIMITS_FILE = DATA_DIR / "seattle_city_limits.geojson"
GRID_LATEST = OUTPUT_DIR / "output_latest.geojson"


# Airspace layer paths (processed)
CLASS_AIRSPACE_FILE = "data/airspace/processed/class_airspace_seattle.geojson"
SUA_FILE = "data/airspace/processed/special_use_airspace_wa.geojson"
STADIUMS_FILE = "data/airspace/processed/stadiums_seattle.geojson"
AIRPORTS_FILE = "data/airspace/processed/airports_seattle.geojson"
UASFM_FILE = "data/airspace/processed/uasfm_seattle.geojson"
SECONDARY_CONSTRAINTS_FILE = "data/airspace/processed/secondary_constraints_seattle.geojson"
STADIUM_BUFFERS_FILE = "data/airspace/processed/stadiums_3nm.geojson"



def find_latest_flights_file() -> Optional[Path]:
    pattern = str(OUTPUT_DIR / "flights_*.json")
    matches = glob.glob(pattern)
    if not matches:
        return None
    # Sort by filename (timestamp in name) and take latest
    matches.sort()
    return Path(matches[-1])


def find_latest_grid_file() -> Optional[Path]:
    """Return output_latest.geojson if present, else latest grid_*.geojson."""
    if GRID_LATEST.exists():
        return GRID_LATEST

    pattern = str(OUTPUT_DIR / "grid_*.geojson")
    matches = glob.glob(pattern)
    if not matches:
        return None
    matches.sort()
    return Path(matches[-1])


def load_flights(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compute_map_center(flights: Dict) -> List[float]:
    lats = []
    lons = []

    for f in flights.get("flights", []):
        for key in ("origin_poi", "destination_poi", "recovery_poi"):
            poi = f.get(key)
            if not poi:
                continue
            lat = poi.get("centroid_lat")
            lon = poi.get("centroid_lon")
            if lat is not None and lon is not None:
                lats.append(float(lat))
                lons.append(float(lon))

    if not lats or not lons:
        # Default to Seattle-ish
        return [47.6062, -122.3321]

    return [sum(lats) / len(lats), sum(lons) / len(lons)]


def add_city_limits_layer(map_obj):
    """Add Seattle city limits as an outline-only boundary (no fill)."""
    city_limits = gpd.read_file(CITY_LIMITS_FILE)

    # Use only the boundary so Leaflet treats it like a line, not a filled polygon
    boundary = city_limits.boundary

    folium.GeoJson(
        boundary,
        name="Seattle City Limits",
        style_function=lambda feature: {
            "color": "#f22424",   
            "weight": 1,         
        },
    ).add_to(map_obj)


def add_flight_routes_layer(m: folium.Map, flights: Dict) -> None:
    # Group all flight legs into a single toggleable layer
    flights_group = folium.FeatureGroup(name="Flights", show=True)

    for f in flights.get("flights", []):
        origin = f.get("origin_poi") or {}
        dest = f.get("destination_poi") or {}
        hub = f.get("recovery_poi") or {}

        try:
            o_lat = float(origin["centroid_lat"])
            o_lon = float(origin["centroid_lon"])
            d_lat = float(dest["centroid_lat"])
            d_lon = float(dest["centroid_lon"])
            h_lat = float(hub["centroid_lat"])
            h_lon = float(hub["centroid_lon"])
        except (KeyError, TypeError, ValueError):
            continue

        tooltip = f.get("flight_id", "flight")
        conflict_legs = set(f.get("obstacle_conflict_legs", []))
        conflict_oas = f.get("obstacle_conflict_oas", [])

        print(
            f"{tooltip}: legs={sorted(conflict_legs)}, obstacles={conflict_oas}"
        )

        legs = [
            ("hub_to_merchant", [[h_lat, h_lon], [o_lat, o_lon]]),
            ("merchant_to_customer", [[o_lat, o_lon], [d_lat, d_lon]]),
            ("customer_to_hub", [[d_lat, d_lon], [h_lat, h_lon]]),
        ]

        for leg_name, leg_points in legs:
            leg_conflict = leg_name in conflict_legs

            line_color = "red" if leg_conflict else "green"
            line_weight = 3 if leg_conflict else 2
            dash = "5,5" if leg_conflict else None

            folium.PolyLine(
                locations=leg_points,
                weight=line_weight,
                color=line_color,
                tooltip=f"{tooltip} ({leg_name})",
                dash_array=dash,
            ).add_to(flights_group)

    flights_group.add_to(m)



def add_obstacles_layer(m: folium.Map) -> None:
    """Add obstacles as a toggleable layer."""
    if not OBSTACLE_FILE.exists():
        return

    gdf = gpd.read_file(OBSTACLE_FILE)

    group = folium.FeatureGroup(name="Obstacles", show=True)

    # ---- 1) Add buffered polygons (true 30m buffers) ----
    folium.GeoJson(
        gdf,
        name="Obstacle Buffers",
        style_function=lambda feature: {
            "color": "red",
            "weight": 2,
            "fill": True,
            "fillOpacity": 0.6,
            "fillColor":"red",
        },
    ).add_to(group)

    for _, row in gdf.iterrows():
        lat = row.get("lat")
        lon = row.get("lon")
        if lat is None or lon is None:
            continue

        agl = row.get("agl_ft")
        obs_type = row.get("obstacle_type", "Obstacle")

        tooltip = (
            f"{obs_type} ({agl} ft AGL)"
            if agl is not None
            else obs_type
        )

        folium.CircleMarker(
            location=[lat, lon],
            radius=4,
            color="red",
            fill=True,
            fill_color="red",
            tooltip=tooltip,
        ).add_to(group)

    group.add_to(m)




def add_airports_layer(map_obj, geojson_path, layer_name="Airports"):
    gdf = gpd.read_file(geojson_path)
    if gdf.crs is None:
        # Airports file should be in WGS84 lat/lon
        gdf = gdf.set_crs(epsg=4326)

    group = folium.FeatureGroup(name=layer_name, show=True)

    # ---- 1) Build buffered polygons around each airport (in meters) ----
    AIRPORT_BUFFER_M = 100  # meters

    # Work on a copy so we can safely mutate geometry
    gdf_buf = gdf.to_crs(epsg=3857).copy()  # project to meters
    gdf_buf["geometry"] = gdf_buf.geometry.buffer(AIRPORT_BUFFER_M)
    gdf_buf = gdf_buf.to_crs(epsg=4326)     # back to lat/lon

    folium.GeoJson(
        gdf_buf,
        name=f"{layer_name} Buffer",
        style_function=lambda feature: {
            "color": "orange",
            "weight": 2,
            "fill": True,
            "fillOpacity": 0.6,
            "fillColor":"red", 
        },
    ).add_to(group)

    # ---- 2) Add point markers at airport locations (for labels/visibility) ----
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.geom_type != "Point":
            continue

        lat = geom.y
        lon = geom.x

        name = row.get("NAME") or row.get("name") or "Airport"
        ident = row.get("ident") or row.get("IDENT") or ""

        label = f"{name}"
        if ident:
            label = f"{name} ({ident})"

        folium.CircleMarker(
            location=[lat, lon],
            radius=5,          # pixels, just for visibility
            color="red",
            popup=label,
            tooltip=label,
        ).add_to(group)

    group.add_to(map_obj)




def add_polygon_layer(
    map_obj,
    geojson_path,
    layer_name,
    color,
    weight=1,
    desired_fields=None,
):
    """Add a polygon/multipolygon GeoJSON as an outline-only layer with hover info."""
    gdf = gpd.read_file(geojson_path)

    # Default fields for "normal" airspace layers if none provided
    if desired_fields is None:
        desired_fields = [
            "ICAO_ID",
            "NAME",
            "LOWER",
            "LOCAL_TYPE",
            "LOWER_VAL",
            "LOWER_CODE",
            "UPPER_VAL",
            "UPPER_CODE",
            "OBJECTID",
            "CEILING",
            "UNIT",
            "APT1_ICAO",
        ]

    # Keep only requested fields that exist
    tooltip_fields = [c for c in desired_fields if c in gdf.columns]

    # Fallback: if none exist (e.g. UASFM has different schema), show all non-geometry fields
    if not tooltip_fields:
        tooltip_fields = [c for c in gdf.columns if c != "geometry"]

    folium.GeoJson(
        gdf,
        name=layer_name,
        style_function=lambda feature: {
            "color": color,
            "weight": weight,
            "fill": False,
            "fillOpacity": 0.6,  # light fill on hover
            "fillColor":"red",
        },
        highlight_function=lambda feature: {
            "weight": weight + 1,
            "fill": True,
            "fillOpacity": 0.6,  # light fill on hover
            "fillColor":"red",
        },
        tooltip=folium.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=[f"{c}:" for c in tooltip_fields],
            sticky=False,
        ),
    ).add_to(map_obj)



def add_secondary_constraints_layer(
    map_obj,
    geojson_path,
    layer_name="Secondary Constraints",
    exclude_names=None,
):
    """
    Add Secondary Constraints-style layer as a Folium layer.

    - Polygons are drawn as-is.
    - LineStrings are buffered to ~30 m and rendered as polygons.
    - Hover shows: name_snake, altitude, priority (if present).
    """
    gdf = gpd.read_file(geojson_path)

    # Optional: filter out features by NAME (e.g. specific stadium buffers)
    if exclude_names and "NAME" in gdf.columns:
        gdf = gdf[~gdf["NAME"].isin(exclude_names)]

    # If filtering removed everything, skip this layer to avoid Folium errors
    if gdf.empty:
        print(f"{layer_name}: no features after filtering; skipping layer.")
        return

    # Approximate 30 m in degrees (good enough near Seattle)
    buffer_deg = 30 / 111_000  # ~0.00027 degrees

    # Buffer corridors (LineString) into polygons
    line_mask = gdf.geometry.geom_type == "LineString"
    if line_mask.any():
        gdf.loc[line_mask, "geometry"] = gdf.loc[line_mask, "geometry"].buffer(buffer_deg)

    # Tooltip fields
    desired_fields = ["name_snake", "altitude", "priority"]
    tooltip_fields = [c for c in desired_fields if c in gdf.columns]

    # Only create a tooltip if there are valid fields
    if tooltip_fields:
        tooltip = folium.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=[f"{c}:" for c in tooltip_fields],
            sticky=False,
        )
    else:
        tooltip = None

    group = folium.FeatureGroup(name=layer_name, show=True)

    folium.GeoJson(
        gdf,
        style_function=lambda feature: {
            "color": "white",
            "weight": 2,
            "fill": True,
            "fillOpacity": 0.6,
            "fillColor": "red",
        },
        highlight_function=lambda feature: {
            "weight": 4,
            "fill": True,
            "fillOpacity": 0.6,
        },
        tooltip=tooltip,
    ).add_to(group)

    group.add_to(map_obj)




def build_map(flights: Dict) -> folium.Map:
    center = compute_map_center(flights)

    m = folium.Map(location=center, zoom_start=10, tiles=None)

 # Local VFR sectional tiles (generated with gdal2tiles)
    folium.TileLayer(
        tiles="../data/tiles_sectional/{z}/{x}/{y}.png",
        attr="Seattle Sectional (Local)",
        name="Sectional (VFR)",
        overlay=False,
        control=True,
        min_zoom=8,
        max_zoom=13,
        opacity=0.6,
        tms=True,     
    ).add_to(m)

    #satellite map
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
        overlay=False,
        control=True,
        opacity=0.6,   

    ).add_to(m)


# Optional: hide the default OpenStreetMap layer
    m.options["layersControl"] = True

    add_city_limits_layer(m)
    add_obstacles_layer(m)       
    add_flight_routes_layer(m, flights)


# --- Airspace layers ---
    add_polygon_layer(
        map_obj=m,
        geojson_path=CLASS_AIRSPACE_FILE,
        layer_name="Class Airspace",
        weight=2,
        color="yellow",
    )

    add_polygon_layer(
        map_obj=m,
        geojson_path=SUA_FILE,
        layer_name="Special Use Airspace (WA)",
        color="red",
    )

    add_polygon_layer(
        map_obj=m,
        geojson_path=UASFM_FILE,
        layer_name="UAS Facility Map",
        color="red", 
    )

    add_secondary_constraints_layer(
        map_obj=m,
        geojson_path=STADIUM_BUFFERS_FILE,
        layer_name="Stadium Buffers",
        exclude_names=["T-Mobile Park", "Lumen Field", "Husky Stadium"],   # to remove buffers
    )

    add_secondary_constraints_layer(
        map_obj=m,
        geojson_path=STADIUMS_FILE,
        layer_name="Stadiums",
    )

    add_secondary_constraints_layer(
        map_obj=m,
        geojson_path=SECONDARY_CONSTRAINTS_FILE,
    )

    add_airports_layer(
        map_obj=m,
        geojson_path=AIRPORTS_FILE,
        layer_name="Airports",
    )

    folium.LayerControl().add_to(m)
    return m



def save_map(m: folium.Map) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"flights_map_{ts}.html"
    m.save(str(out_path))
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize UTM flight routes on a Folium map."
    )
    parser.add_argument(
        "--flights",
        type=str,
        default=None,
        help="Path to flights JSON (default: latest output/flights_*.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.flights:
        flights_path = Path(args.flights)
    else:
        flights_path = find_latest_flights_file()
        if flights_path is None:
            raise SystemExit(
                "No flights_*.json found in output/. "
                "Run flight_generator.py first."
            )

    if not flights_path.exists():
        raise SystemExit(f"Flights file not found: {flights_path}")

    flights = load_flights(flights_path)
    m = build_map(flights)
    out_path = save_map(m)

    print(f"Map written to: {out_path}")
    print("Open this file in your browser to view flight routes.")


if __name__ == "__main__":
    main()
