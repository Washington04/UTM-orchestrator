# grid_generator.py
# Empty module for grid generation.
# Add functions, classes, and tests for generating grids here.
"""
Drone Flight Grid Generator
- Input: bounding box in lat/lon (EPSG:4326) and cell size in meters.
- Output: GeoJSON of grid cells in EPSG:4326.

Usage example:
    python grid_generator.py --north 48.0 --south 47.0 --west -122.5 --east -121.5 --cell 100 \
        --out output/grid_1km.geojson
"""

import argparse
import math
import os
import geopandas as gpd
from shapely.geometry import box
from pyproj import CRS

def _utm_epsg_for_latlon(lat: float, lon: float) -> str:
    """
    Pick a local UTM CRS for good meter-based tiling.
    """
    zone = int(math.floor((lon + 180) / 6) + 1)
    if lat >= 0:
        return f"EPSG:{32600 + zone}"  # WGS84 / UTM zone N
    else:
        return f"EPSG:{32700 + zone}"  # WGS84 / UTM zone S

def build_grid(north: float, south: float, west: float, east: float, cell_m: float) -> gpd.GeoDataFrame:
    if not (south < north and west < east):
        raise ValueError("Invalid bounds: ensure south<north and west<east.")
    if cell_m <= 0:
        raise ValueError("Cell size (meters) must be > 0.")

    # Bounding box in geographic CRS
    bounds_gdf = gpd.GeoDataFrame(geometry=[box(west, south, east, north)], crs="EPSG:4326")

    # Choose a UTM CRS around the bbox center for meter-accurate gridding
    centroid = bounds_gdf.geometry.iloc[0].centroid
    utm_epsg = _utm_epsg_for_latlon(lat=centroid.y, lon=centroid.x)

    # Reproject bounds to UTM (meters)
    bounds_utm = bounds_gdf.to_crs(utm_epsg)
    minx, miny, maxx, maxy = bounds_utm.total_bounds

    # Build tiles in UTM coordinates
    cells = []
    y = miny
    while y < maxy:
        x = minx
        while x < maxx:
            x2 = min(x + cell_m, maxx)
            y2 = min(y + cell_m, maxy)
            # Skip degenerate tiles
            if (x2 - x) > 0 and (y2 - y) > 0:
                cells.append(box(x, y, x2, y2))
            x += cell_m
        y += cell_m

    gdf_utm = gpd.GeoDataFrame(
        {"cell_id": list(range(1, len(cells) + 1))},
        geometry=cells,
        crs=utm_epsg
    )

    # Back to EPSG:4326 for universal GeoJSON output
    gdf_wgs84 = gdf_utm.to_crs("EPSG:4326")
    return gdf_wgs84

def main():
    ap = argparse.ArgumentParser(description="Generate a geospatial grid over a lat/lon bounding box.")
    ap.add_argument(
    "--boundary",
    type=str,
    required=True,
    help="Boundary polygon (GeoJSON/SHP). Grid will be clipped to this shape."
)
    ap.add_argument("--cell",  type=float, required=True, help="Cell size in meters (e.g., 100)")
    ap.add_argument("--out",   type=str,   default="output/grid.geojson", help="Output GeoJSON path")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

   minx, miny, maxx, maxy = bounds_from_boundary(args.boundary)

gdf = build_grid(
    north=maxy,
    south=miny,
    west=minx,
    east=maxx,
    cell_m=args.cell,
)
gdf = clip_to_boundary(gdf, args.boundary)
    gdf.to_file(args.out, driver="GeoJSON")
    print(f"[OK] Wrote {len(gdf)} cells to {args.out}")

if __name__ == "__main__":
    main()
