import geopandas as gpd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DOF_WA = ROOT / "data" / "obstacles" / "faa_dof_wa.geojson"
SEATTLE_AOI = ROOT / "data" / "seattle_city_limits.geojson"
OUTPUT = ROOT / "data" / "obstacles" / "faa_dof_seattle.geojson"

MIN_AGL_FT = 368  # 400 ft - ~10m vertical buffer

def main():
    print(f"Loading statewide DOF: {DOF_WA}")
    dof = gpd.read_file(DOF_WA)
    print(f"Statewide obstacles (all AGL): {len(dof)}")

    # Make sure DOF has a CRS
    if dof.crs is None:
        # DOF should be WGS84 lat/lon
        dof.set_crs(epsg=4326, inplace=True)
        print(f"Set DOF CRS to: {dof.crs}")

    print(f"Loading Seattle AOI: {SEATTLE_AOI}")
    seattle = gpd.read_file(SEATTLE_AOI)
    if seattle.crs is None:
        seattle.set_crs(epsg=4326, inplace=True)
    seattle = seattle.to_crs(dof.crs)

    print("Clipping obstacles to Seattle AOI...")
    clipped = gpd.clip(dof, seattle)
    print(f"Obstacles in Seattle AOI (all AGL): {len(clipped)}")

    # Filter out obstacles below 218 ft AGL
    if "agl_ft" not in clipped.columns:
        raise KeyError("Expected 'agl_ft' column in DOF GeoDataFrame")
    
    filtered = clipped[clipped["agl_ft"] >= MIN_AGL_FT].copy()
    print(f"Obstacles in Seattle AOI (AGL >= {MIN_AGL_FT} ft): {len(filtered)}")
    
    BUFFER_M = 30  #30m obstacle buffer
    print(f"Applying {BUFFER_M} m lateral buffer...")

    filtered_3857 = filtered.to_crs(epsg=3857)
    filtered_3857["geometry"] = filtered_3857.geometry.buffer(BUFFER_M)
    buffered = filtered_3857.to_crs(epsg=4326)  # back to WGS84

    print(f"Buffered obstacle count: {len(buffered)}")
    print(f"Buffered CRS: {buffered.crs}")
    print(f"Example geom type: {buffered.geometry.iloc[0].geom_type}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    buffered.to_file(OUTPUT, driver="GeoJSON")

    print(f"Output saved to: {OUTPUT}")

if __name__ == "__main__":
    main()