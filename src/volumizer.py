#!/usr/bin/env python3
"""
Volumizer: Create 4D volumes (spatial + altitude + time) associated with flight paths.

A 4D volume consists of:
- Polygon: Horizontal footprint (e.g., buffered path)
- Vertical dimension: Min/Max AGL (Above Ground Level)
- Time component: Start/End time

Usage:
    python src/volumizer.py --path path.json --output volumes.json
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple
import geopandas as gpd
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union

# Constants
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DATA_DIR = ROOT / "data"

class Volume4D:
    def __init__(self, polygon: Polygon, min_agl: float, max_agl: float, start_time: datetime, end_time: datetime):
        self.polygon = polygon
        self.min_agl = min_agl
        self.max_agl = max_agl
        self.start_time = start_time
        self.end_time = end_time

    def to_dict(self) -> Dict:
        return {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [list(self.polygon.exterior.coords)]
            },
            "properties": {
                "min_agl": self.min_agl,
                "max_agl": self.max_agl,
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat()
            }
        }

    def overlaps(self, other: 'Volume4D') -> bool:
        """Check if this volume overlaps with another in space and time."""
        spatial_overlap = self.polygon.intersects(other.polygon)
        time_overlap = (self.start_time < other.end_time) and (other.start_time < self.end_time)
        alt_overlap = (self.min_agl < other.max_agl) and (other.min_agl < self.max_agl)
        return spatial_overlap and time_overlap and alt_overlap

def create_volumes_from_path(path: List[Dict], buffer_m: float = 50, min_agl: float = 30, max_agl: float = 120,
                           duration_min: int = 10) -> List[Volume4D]:
    """
    Create 4D volumes along a flight path.

    Args:
        path: List of points with 'lat', 'lon', 'alt_agl', 'time'
        buffer_m: Horizontal buffer in meters
        min_agl/max_agl: Altitude range if not per-point
        duration_min: Time duration per segment in minutes

    Returns:
        List of Volume4D objects
    """
    volumes = []
    for i, point in enumerate(path):
        lat, lon = point['lat'], point['lon']
        alt = point.get('alt_agl', (min_agl + max_agl) / 2)
        time = datetime.fromisoformat(point['time']) if isinstance(point['time'], str) else point['time']

        # Create a small polygon around the point (or segment)
        if i < len(path) - 1:
            next_point = path[i+1]
            line = LineString([(lon, lat), (next_point['lon'], next_point['lat'])])
            buffered = line.buffer(buffer_m / 111320)  # Rough degrees to meters conversion
        else:
            buffered = Polygon([(lon - buffer_m/111320, lat - buffer_m/111320),
                               (lon + buffer_m/111320, lat - buffer_m/111320),
                               (lon + buffer_m/111320, lat + buffer_m/111320),
                               (lon - buffer_m/111320, lat + buffer_m/111320)])

        # Altitude range: use point alt +/- some margin
        alt_margin = 10
        vol_min_agl = max(0, alt - alt_margin)
        vol_max_agl = alt + alt_margin

        # Time: segment duration
        end_time = time + timedelta(minutes=duration_min)

        volume = Volume4D(buffered, vol_min_agl, vol_max_agl, time, end_time)
        volumes.append(volume)

    return volumes

def save_volumes(volumes: List[Volume4D], output_path: Path):
    features = [v.to_dict() for v in volumes]
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(geojson, f, indent=2)
    print(f"Saved {len(volumes)} volumes to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create 4D volumes from flight paths")
    parser.add_argument("--path", required=True, help="JSON file with flight path")
    parser.add_argument("--output", default="output/volumes.json", help="Output GeoJSON file")
    parser.add_argument("--buffer", type=float, default=50, help="Horizontal buffer in meters")
    args = parser.parse_args()

    # Load path from JSON (assume format like [{"lat": ..., "lon": ..., "alt_agl": ..., "time": ...}])
    with open(args.path) as f:
        path_data = json.load(f)

    volumes = create_volumes_from_path(path_data, buffer_m=args.buffer)
    save_volumes(volumes, Path(args.output))