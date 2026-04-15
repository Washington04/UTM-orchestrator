# Operational Intent Builder Plan

## Overview
Build a pipeline that takes a start/end location in lat/lon and generates a complete operational intent with:
1. Waypoints (path from origin to destination)
2. 4D Volumes (spatial + altitude + time)
3. KML export for Google Earth visualization

---

## Pipeline Flow

```
User Input (Start/End Lat/Lon)
    ↓
Waypoint Engine (Generate path via A* on grid)
    ↓
Volumizer (Create 4D volumes around waypoints)
    ↓
KML Exporter (Convert volumes to KML for Google Earth)
    ↓
Output: flight_volumes.kml
```

---

## Components

### 1. Waypoint Engine (`src/waypoint_engine.py`)
**Purpose**: Generate a series of waypoints from origin to destination.

**Input**:
- `origin_lat, origin_lon` (float)
- `dest_lat, dest_lon` (float)
- Optional: `altitude_agl` (default ~100m), `cruise_speed_ms` (default 15 m/s)

**Process**:
- Load Queen Anne AOI and obstacles (from `neighborhood_graph.py` logic)
- Snap origin/dest to valid grid nodes
- Run A* pathfinding to find optimal path
- Convert path nodes to waypoints with lat/lon/alt/time
- Time calculated based on distance and cruise speed

**Output**: List of waypoint dicts
```json
[
  {"lat": 47.6336, "lon": -122.3572, "alt_agl": 100, "time": "2026-04-15T10:00:00Z"},
  {"lat": 47.6330, "lon": -122.3565, "alt_agl": 100, "time": "2026-04-15T10:00:30Z"},
  ...
]
```

**Notes**:
- Reuse grid and obstacle loading from `neighborhood_graph.py`
- Keep waypoint generation modular for future extensions (climb/descent profiles, speed variation)

---

### 2. Volumizer (`src/volumizer.py`)
**Purpose**: Create 4D volumes (polygon + altitude + time) around the waypoint path.

**Input**:
- Waypoint list (from Waypoint Engine)
- `horizontal_buffer_m` (default 50m)
- `vertical_margin_agl` (default ±10m around waypoint altitude)
- `segment_duration_min` (default 1 min per waypoint segment)

**Process**:
- For each waypoint segment, create a buffered polygon
- Assign altitude range: `[waypoint_alt - margin, waypoint_alt + margin]`
- Assign time range based on segment duration
- Create `Volume4D` objects

**Output**: List of `Volume4D` objects (can serialize to GeoJSON or pass directly to KML exporter)

**Notes**:
- Do NOT run conflict checks yet (will add later)
- Handle coordinate transformations (lat/lon ↔ meters for buffering)

---

### 3. KML Exporter (`src/kml_exporter.py`)
**Purpose**: Convert 4D volumes to KML format for Google Earth.

**Input**:
- List of `Volume4D` objects

**Process**:
- Use `simplekml` library to create KML
- For each volume:
  - Create Placemark with extruded polygon (uses altitude)
  - Add TimeSpan element (start_time, end_time)
  - Apply styling (color, transparency)
  - Add description with altitude range
- Write to `output/flight_volumes.kml`

**Output**: `output/flight_volumes.kml` (importable into Google Earth)

**Notes**:
- Add `simplekml` to `requirements.txt`
- Altitude in KML is above MSL (mean sea level), so we need to add terrain elevation if available later
- Group volumes into a Folder for organizational purposes

---

### 4. Main Orchestrator (`src/build_operational_intent.py`)
**Purpose**: Single entry point that coordinates the full pipeline.

**Input**:
- CLI arguments: `--start LAT,LON --end LAT,LON`
- Optional: output path, altitude, buffer size, etc.

**Process**:
1. Parse inputs
2. Call Waypoint Engine → get waypoints
3. Call Volumizer → get volumes
4. Call KML Exporter → save KML
5. Print summary (number of waypoints, volumes, output file path)

**Usage**:
```bash
python src/build_operational_intent.py --start 47.6336,-122.3572 --end 47.6311,-122.3503
```

**Output**: Success message + path to generated KML

---

## Key Design Decisions

- **No Mock API**: Keep it simple; CLI input directly for now
- **No Conflict Detection Yet**: Will add in Phase 2
- **Modular**: Each component standalone and testable
- **Reuse Existing Code**: Build on `neighborhood_graph.py` for grid/obstacle logic
- **CRS Consistency**: Use EPSG:4326 (lat/lon) for input/output; EPSG:26910 (UTM) internally for meters

---

## Implementation Order

1. **Waypoint Engine** - Extract/extend logic from `neighborhood_graph.py`
2. **Volumizer** - Refine existing `volumizer.py`
3. **KML Exporter** - Create new, use `simplekml`
4. **Orchestrator** - Tie it all together

---

## Testing

- Test with Queen Anne AOI (origin/dest within boundaries)
- Generate KML and open in Google Earth
- Verify waypoints, volumes, and timestamps are correct

---

## Future Enhancements

- Conflict detection (volume overlaps)
- Airspace integration (respect restricted zones)
- Real-time API integration
- Web UI/frontend
- Altitude profiles (climb/descent)
- Wind integration for time estimation
