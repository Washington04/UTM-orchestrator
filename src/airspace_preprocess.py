#!/usr/bin/env python3
"""
Preprocess FAA airspace layers for UTM Orchestrator.

Layers:
- class_airspace.geojson       → class_airspace_seattle.geojson
- special_use_airspace.geojson → special_use_airspace_wa.geojson
- stadiums.geojson             → stadiums_seattle.geojson
- airports.geojson             → airports_seattle.geojson

Rules:
- Class airspace, stadiums, airports:
    * optionally filter STATE="WA"
    * load with Seattle bbox for performance
    * clip to Seattle city limits polygon
- Special Use Airspace (SUA):
    * filter STATE="WA"
    * NO bbox (load full file)
    * NO clip (keep WA-wide)
"""

import geopandas as gpd
from pathlib import Path

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

DATA_DIR = Path("data") / "airspace"
RAW_DIR = DATA_DIR / "raw"
OUT_DIR = DATA_DIR / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Seattle city limits polygon
SEATTLE_AOI_PATH = Path("data/seattle_city_limits.geojson")

# ---------------------------------------------------------------------
# Load Seattle AOI
# ---------------------------------------------------------------------

print(f"Loading Seattle AOI from: {SEATTLE_AOI_PATH}")
seattle_aoi = gpd.read_file(SEATTLE_AOI_PATH).to_crs("EPSG:4326")
# Shapely 2.x: use union_all instead of deprecated unary_union
aoi_geom = seattle_aoi.union_all()

# Seattle-ish bbox to speed loading of huge national datasets
# (lon_min, lat_min, lon_max, lat_max)
SEATTLE_BBOX = (-122.6, 47.3, -122.1, 47.9)


def read_with_bbox(path: Path) -> gpd.GeoDataFrame:
    """Read with a bounding box to avoid loading entire U.S. datasets."""
    return gpd.read_file(path, bbox=SEATTLE_BBOX).to_crs("EPSG:4326")


def read_full(path: Path) -> gpd.GeoDataFrame:
    """Read the full dataset (no bbox)."""
    return gpd.read_file(path).to_crs("EPSG:4326")


# ---------------------------------------------------------------------
# Generic clip + filter function
# ---------------------------------------------------------------------

def clip_and_save(
    name_in,
    name_out,
    state_field=None,
    state_value=None,
    do_clip=True,
    use_bbox=True,
):
    """
    Generic preprocessing helper.

    Parameters
    ----------
    name_in : str
        Input filename in data/airspace/raw
    name_out : str
        Output filename in data/airspace/processed
    state_field : str | None
        Column name to filter on (e.g., "STATE"), if present
    state_value : str | None
        Value for state_field to keep (e.g., "WA")
    do_clip : bool
        Whether to clip to the Seattle AOI polygon
    use_bbox : bool
        Whether to use the Seattle bbox when reading the file
    """
    src = RAW_DIR / name_in
    dst = OUT_DIR / name_out

    print(f"\nProcessing {src.name} → {dst.name}")

    # Choose read method
    if use_bbox:
        gdf = read_with_bbox(src)
        print(f"  Loaded with bbox: {len(gdf)} features")
    else:
        gdf = read_full(src)
        print(f"  Loaded full dataset: {len(gdf)} features")

    # Optional state filter
    if state_field and state_field in gdf.columns and state_value is not None:
        before = len(gdf)
        gdf = gdf[gdf[state_field] == state_value]
        print(f"  State filter {state_field}={state_value}: {before} → {len(gdf)} features")

    # Optional clip to Seattle AOI polygon
    if do_clip:
        before = len(gdf)
        gdf = gdf.clip(aoi_geom)
        print(f"  Clip to Seattle AOI: {before} → {len(gdf)} features")

    # Save processed dataset
    gdf.to_file(dst, driver="GeoJSON")
    print(f"  Final saved: {len(gdf)} features")


# ---------------------------------------------------------------------
# Main Processing
# ---------------------------------------------------------------------

def main() -> None:
    # 1) Class Airspace – WA (optional), bbox, clipped to Seattle
    clip_and_save(
        name_in="class_airspace.geojson",
        name_out="class_airspace_seattle.geojson",
        state_field="STATE",
        state_value="WA",
        do_clip=True,
        use_bbox=True,
    )

    # 2) Special Use Airspace (SUA) – WA-only, NO bbox, NO clip (WA-wide)
    clip_and_save(
        name_in="special_use_airspace.geojson",
        name_out="special_use_airspace_wa.geojson",
        state_field="STATE",
        state_value="WA",
        do_clip=False,   # keep full WA extent
        use_bbox=False,  # don't restrict to Seattle bbox
    )

    # 3) Stadiums – WA-only, bbox, clipped to Seattle
    clip_and_save(
        name_in="stadiums.geojson",
        name_out="stadiums_seattle.geojson",
        state_field="STATE",
        state_value="WA",
        do_clip=True,
        use_bbox=True,
    )

    # 4) Airports – WA-only, bbox, clipped to Seattle
    clip_and_save(
        name_in="airports.geojson",
        name_out="airports_seattle.geojson",
        state_field="STATE",
        state_value="WA",
        do_clip=True,
        use_bbox=True,
    )


if __name__ == "__main__":
    main()
