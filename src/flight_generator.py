#!/usr/bin/env python3
"""
Generate synthetic operational intents (flights) from POIs.

Usage (from root):
  python flight_generator.py --count 10
  python flight_generator.py --count 10 --output output/flights_custom.json
"""

import argparse
import csv
import json
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import geopandas as gpd
from shapely.geometry import LineString
from pathlib import Path

POI_FILE = "data/points_of_interest.csv"
OBSTACLE_FILE = Path("data/obstacles/faa_dof_seattle.geojson")
DEFAULT_OUTPUT_DIR = "output"


class POI:
    def __init__(
        self,
        poi_id: str,
        poi_type: str,
        poi_name: str,
        cell_id: str,
        centroid_lat: float,
        centroid_lon: float,
    ):
        self.poi_id = poi_id
        self.poi_type = poi_type
        self.poi_name = poi_name
        self.cell_id = cell_id
        self.centroid_lat = centroid_lat
        self.centroid_lon = centroid_lon

    def to_dict(self) -> Dict:
        return {
            "poi_id": self.poi_id,
            "poi_type": self.poi_type,
            "poi_name": self.poi_name,
            "cell_id": self.cell_id,
            "centroid_lat": self.centroid_lat,
            "centroid_lon": self.centroid_lon,
        }

def segment_conflicting_obstacles(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    obstacles: gpd.GeoDataFrame,
) -> List[str]:
    """
    Returns a list of OAS IDs for obstacles whose buffered polygon
    intersects the segment from (lat1, lon1) to (lat2, lon2).
    """
    if obstacles.empty:
        return []

    # Shapely uses (lon, lat) order
    line = LineString([(lon1, lat1), (lon2, lat2)])

    # Intersect test over all buffered polygons
    mask = obstacles.intersects(line)
    if not mask.any():
        return []

    # Prefer FAA's 'oas' ID if present
    if "oas" in obstacles.columns:
        return obstacles.loc[mask, "oas"].astype(str).tolist()

    # Fallback to index if 'oas' missing for some reason
    return [str(i) for i in obstacles.index[mask]]


def load_obstacle_buffers() -> gpd.GeoDataFrame:
    """Load buffered obstacles created by obstacle_preprocess.py."""
    if not OBSTACLE_FILE.exists():
        print(f"Warning: obstacle file not found: {OBSTACLE_FILE}")
        return gpd.GeoDataFrame()  # empty fallback

    obstacles = gpd.read_file(OBSTACLE_FILE)

    # Ensure valid CRS for geometry checks
    if obstacles.crs is None:
        obstacles.set_crs(epsg=4326, inplace=True)

    return obstacles


def load_pois(path: str = POI_FILE) -> Dict[str, List[POI]]:
    merchants: List[POI] = []
    customers: List[POI] = []
    hubs: List[POI] = []

    if not os.path.exists(path):
        raise FileNotFoundError(f"POI file not found: {path}")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=",")
        required_cols = {
            "poi_id",
            "poi_type",
            "poi_name",
            "cell_id",
            "centroid_lat",
            "centroid_lon",
        }
        missing = required_cols - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"POI file is missing required columns: {missing}")

        for row in reader:
            poi_type = (row["poi_type"] or "").strip().lower()
            poi = POI(
                poi_id=row["poi_id"],
                poi_type=poi_type,
                poi_name=row["poi_name"],
                cell_id=row["cell_id"],
                centroid_lat=float(row["centroid_lat"]),
                centroid_lon=float(row["centroid_lon"]),
            )

            if poi_type == "merchant":
                merchants.append(poi)
            elif poi_type == "customer":
                customers.append(poi)
            elif poi_type == "hub":
                hubs.append(poi)
            else:
                # Ignore unknown types for now
                continue

    if not merchants:
        raise ValueError("No merchant POIs found in pois.csv (poi_type='merchant').")
    if not customers:
        raise ValueError("No customer POIs found in pois.csv (poi_type='customer').")
    if not hubs:
        raise ValueError("No hub POIs found in pois.csv (poi_type='hub').")

    return {"merchants": merchants, "customers": customers, "hubs": hubs}


def generate_flight_id(index: int, prefix: str = "FLIGHT") -> str:
    return f"{prefix}_{index:05d}"


def generate_departure_time(
    base_time: Optional[datetime] = None,
    min_offset_minutes: int = 0,
    max_offset_minutes: int = 30,
) -> str:
    if base_time is None:
        base_time = datetime.now(timezone.utc)

    offset = timedelta(
        minutes=random.randint(min_offset_minutes, max_offset_minutes)
    )
    dt = base_time + offset
    # ISO 8601 with Z
    return dt.isoformat().replace("+00:00", "Z")


def generate_operational_intents(
    pois: Dict[str, List[POI]],
    count: int,
    cruise_altitude_ft: int = 250,
    speed_mps: float = 25.0,
    route_strategy: str = "straight_line",
) -> List[Dict]:
    
    obstacles = load_obstacle_buffers()

    merchants = pois["merchants"]
    customers = pois["customers"]
    hubs = pois["hubs"]

    base_time = datetime.now(timezone.utc)
    flights: List[Dict] = []

    for i in range(1, count + 1):
        merchant = random.choice(merchants)
        customer = random.choice(customers)
        hub = random.choice(hubs)

        conflict_legs: List[str] = []
        conflict_obstacles: set[str] = set()


        # hub -> merchant
        ids = segment_conflicting_obstacles(
            hub.centroid_lat,
            hub.centroid_lon,
            merchant.centroid_lat,
            merchant.centroid_lon,
            obstacles,
        )
        if ids:
            conflict_legs.append("hub_to_merchant")
            conflict_obstacles.update(ids)

        # merchant -> customer
        ids = segment_conflicting_obstacles(
            merchant.centroid_lat,
            merchant.centroid_lon,
            customer.centroid_lat,
            customer.centroid_lon,
            obstacles,
        )
        if ids:
            conflict_legs.append("merchant_to_customer")
            conflict_obstacles.update(ids)

        # customer -> hub
        ids = segment_conflicting_obstacles(
            customer.centroid_lat,
            customer.centroid_lon,
            hub.centroid_lat,
            hub.centroid_lon,
            obstacles,
        )
        if ids:
            conflict_legs.append("customer_to_hub")
            conflict_obstacles.update(ids)

        has_conflict = bool(conflict_legs)
    

        flight_id = generate_flight_id(i)
        scheduled_departure_utc = generate_departure_time(
            base_time=base_time,
            min_offset_minutes=0,
            max_offset_minutes=30,
        )

        intent = {
            "flight_id": flight_id,
            "origin_poi_id": merchant.poi_id,
            "destination_poi_id": customer.poi_id,
            "recovery_poi_id": hub.poi_id,
            "origin_cell_id": merchant.cell_id,
            "destination_cell_id": customer.cell_id,
            "recovery_cell_id": hub.cell_id,
            "scheduled_departure_utc": scheduled_departure_utc,
            "cruise_altitude_ft": cruise_altitude_ft,
            "speed_mps": speed_mps,
            "route_strategy": route_strategy,
            "status": "conflict_obstacle" if has_conflict else "planned",
            "has_obstacle_conflict": has_conflict,
            "obstacle_conflict_legs": conflict_legs,
            "obstacle_conflict_oas": sorted(conflict_obstacles),
            # Optional embedded POI details
            "origin_poi": merchant.to_dict(),
            "destination_poi": customer.to_dict(),
            "recovery_poi": hub.to_dict(),
        }

        flights.append(intent)

    # --- Summary of conflicts ---
    conflict_count = sum(1 for f in flights if f.get("has_obstacle_conflict", False))
    print(f"Detected {conflict_count} obstacle conflicts out of {len(flights)} flights.")

    return flights


def write_flights_to_file(flights: List[Dict], output_path: Optional[str] = None) -> str:
    if output_path is None:
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(DEFAULT_OUTPUT_DIR, f"flights_{ts}.json")
    else:
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at_utc": datetime.utcnow().isoformat() + "Z",
                "flight_count": len(flights),
                "flights": flights,
            },
            f,
            indent=2,
        )

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic UTM operational intents from POIs."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of flights to generate (default: 20)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path (default: output/flights_YYYYMMDD_HHMMSS.json)",
    )
    parser.add_argument(
        "--poi-file",
        type=str,
        default=POI_FILE,
        help="Path to POIs CSV file (default: data/pois.csv)",
    )
    parser.add_argument(
        "--altitude-ft",
        type=int,
        default=250,
        help="Default cruise altitude in feet (default: 250)",
    )
    parser.add_argument(
        "--speed-mps",
        type=float,
        default=25.0,
        help="Default airspeed in meters per second (default: 25.0)",
    )
    parser.add_argument(
        "--route-strategy",
        type=str,
        default="straight_line",
        help="Route strategy label to embed in intents (default: straight_line)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    pois = load_pois(args.poi_file)

    flights = generate_operational_intents(
        pois=pois,
        count=args.count,
        cruise_altitude_ft=args.altitude_ft,
        speed_mps=args.speed_mps,
        route_strategy=args.route_strategy,
    )

    output_path = write_flights_to_file(flights, args.output)
    print(f"Generated {len(flights)} flights → {output_path}")


if __name__ == "__main__":
    main()
