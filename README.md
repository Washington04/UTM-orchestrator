**UTM Orchestrator**

_A lightweight, standards-aligned UAS Traffic Management (UTM) simulation environment_

UTM Orchestrator is a learning project to explore UTM technical challenges, geospatial approaches, and airspace interoperability. Contributions, suggestions, and discussions are welcome. Please add them to UTM-orchestrator/community_notes. 

***

**Overview**

**UTM Orchestrator** is a developing simulation framework designed to model a full UAS Traffic Management (UTM) ecosystem in the Seattle metropolitan area.

The system generates:
- Geographical operating areas (grid-based, meter-accurate)
- Flight planning with spatial pathfinding (A*, BFS on neighborhood graphs)
- Operational intents with 4D volumes (spatial + altitude + time)
- Static & dynamic constraints (Obstacles, Stadium TFRs, Open-air assemblies, TFRs)
- Strategic deconfliction workflows
- KML export for Google Earth visualization

The goal is to provide a safe environment to explore how UTM services, implemented in accordance with industry consensus standards, enable safe, scalable, and transparent shared airspace operations.

This project is not intended to be an operational USS, but rather a research and learning tool that mirrors the structure of basic UTM systems.

***

**Objectives**

- Model BVLOS delivery operations in dense urban airspace
- Implement the foundational elements of a UAS Service Supplier (USS) / Airspace Data Service Provider (ADSP)
- Support simulation of strategic conflict detection, intent sharing, and inter-USS coordination
- Provide a platform for evaluating shared airspace concepts inspired by the US UTM Implementation
- Allow users to visualize routes, grids, and constraints directly within the workflow

***

**Standards & Guidance Referenced**

UTM Orchestrator is designed with reference to the FAA, ASTM, and international guidance that shapes basic UTM systems:
- ASTM F3548-21 – USS Interoperability
- (draft) 14 CFR Part 108 – UAS Operating Rules (proposed)
- (draft) 14 CFR Part 146 & AC 146-1 – Airspace Data Service Providers (proposed)
- U-Space regulatory guidance (EU)
- Shared Airspace / Strategic Coordination concepts from the US UTM Implementation

***

**Current Capabilities**

**Geospatial Grid Generation** (`src/grid_generator.py`)
- Generates a meter-accurate grid over Seattle using:
  - Dynamic UTM projection
  - Polygon clipping to boundary
  - Unique cell_ids
  - Rounded centroid coordinates
- Outputs clean GeoJSON for UTM-style visualization

**Neighborhood Graph & Pathfinding** (`src/neighborhood_graph.py`)
- Builds 8-connected grid graphs within an Area of Interest (AOI)
- Implements:
  - BFS (Breadth-First Search)
  - A* pathfinding with Euclidean heuristics
- Avoids obstacles loaded from FAA DOF (Digital Obstacle File)
- Outputs interactive Folium map with path visualization

**Points of Interest (POI) System** (`src/poi_generator.py`)
- Generates synthetic:
  - hub locations
  - merchant pickup sites
  - customer delivery points
- Outputs both CSV and GeoJSON for visual overlays

**Flight Generator** (`src/flight_generator.py`)
- Creates realistic delivery missions:
  - hub → merchant → customer → hub sequences
- Associates flights with grid cells + coordinates
- Outputs operational intent objects (JSON)

**METAR Weather Integration** (`src/weather_service.py`)
- Fetches METAR observations from aviationweather.gov
- Stores normalized weather output in `output/weather`
- Adds binary hazard checks for:
  - `lightning`
  - `windspeed_25kts`
  - `windgusts_25kts`
  - `low_visibility`
  - `low_ceiling`
- Sets `available` to `true` only when all hazard flags are `0`, otherwise `false`

**Operational Intent Pipeline** (In Development)
- **Waypoint Engine** (`src/waypoint_engine.py`): Takes origin/destination lat/lon, generates waypoints using A* pathfinding
- **Volumizer** (`src/volumizer.py`): Creates 4D volumes (polygon + altitude + time) around flight paths
- **KML Exporter** (`src/kml_exporter.py`): Converts volumes to KML for Google Earth import
- **Orchestrator** (`src/build_operational_intent.py`): Single CLI entry point for end-to-end pipeline

**Visualization Support**
- Native geospatial preview in VS Code
- GeoJSON-based layered visualization
- Folium interactive maps
- KML export for Google Earth
- Grid + POI + flight path overlays for operational alignment

**Constraint Data**
- FAA Digital Obstacle File (DOF) processing
- Airspace classification layers (Class B, C, D, etc.)
- Special Use Airspace (SUA)
- Stadium Temporary Flight Restrictions (TFRs)
- UASFM (UAS Facility Map) constraints
- Secondary constraints (railroads, stadiums with 3nm buffers)

***

**In Development / Roadmap**

**Phase 1: Operational Intent Builder** (Current)
- ✅ Waypoint generation via A* pathfinding
- ✅ 4D volume creation (polygon + altitude + time)
- ✅ KML export for Google Earth
- ⏳ End-to-end orchestrator CLI

**Phase 2: Strategic Deconfliction**
- Identify conflicts using:
  - Spatial overlap (volume intersection)
  - Time window conflicts
  - Altitude separation rules
- Apply "US Shared Airspace" guiding principles
- Volume conflict detection algorithm

**Phase 3: Constraint Integration**
- Dynamic airspace respecting:
  - No-fly zones / Special Use Airspace
  - Temporary flight restrictions
  - Weather constraints
- Integrate real-time constraint updates

**Phase 4: Multi-Flight Coordination**
- Strategic coordination between multiple flights
- Intent sharing and negotiation
- Conflict resolution strategies
- Priority-based deconfliction

***

**Long-Term Vision**
- UTM Orchestrator aims to serve as a sandbox environment for:
  - Exploring tradeoffs in UTM decisions
  - Strategic coordination testing
  - Rapid prototyping of UTM concepts
  - Web-based operational interface
  - Real-time simulation and visualization
  - Integration with real airspace data feeds

Goal is to provide a simplified environment mirroring the ecosystem emerging from UTM Shared Airspace Implementation and ASTM interoperability standards.

***

**Secondary Constraints (User-Defined Airspace Conditions)**

Secondary Constraints are custom airspace restrictions which represent quiet zones, voluntary avoidance areas, temporary corridors, safety buffers, or any other non-regulatory constraint relevant to UTM.

All constraints live inside:
data/airspace/processed/secondary_constraints_seattle.geojson

Each constraint is a Polygon (area) or a LineString (corridor).
Corridors are automatically buffered to 30 meters during visualization.

**Schema**

Every Secondary Constraint must include:

```json
{
  "name_snake": "identifier_in_snake_case",
  "altitude": 400,
  "priority": "high"
}
```

- name_snake: short identifier in snake_case
- altitude: integer altitude limit (feet)
- priority: "low", "medium", or "high"
- Coordinates must be standard GeoJSON:
  - [longitude, latitude]
  - CRS: EPSG:4326

**Polygon Example**
```json
{
  "type": "Feature",
  "properties": {
    "name_snake": "harborview_quiet_zone",
    "altitude": 400,
    "priority": "high"
  },
  "geometry": {
    "type": "Polygon",
    "coordinates": [
      [
        [-122.3235, 47.6055],
        [-122.3205, 47.6055],
        [-122.3205, 47.6025],
        [-122.3235, 47.6025],
        [-122.3235, 47.6055]
      ]
    ]
  }
}
```

**Corridor Example (auto-buffered 30m)**
```json
{
  "type": "Feature",
  "properties": {
    "name_snake": "elliott_bay_corridor_eastwest",
    "altitude": 300,
    "priority": "medium"
  },
  "geometry": {
    "type": "LineString",
    "coordinates": [
      [-122.3600, 47.6050],
      [-122.3400, 47.6050],
      [-122.3200, 47.6050]
    ]
  }
}
```

**Updating Secondary Constraints**

Edit the GeoJSON file:
```
data/airspace/processed/secondary_constraints_seattle.geojson
```

Add, modify, or delete a Feature.

Run:
```bash
python src/visualizer.py
```

Open the most recently generated map in `output/` and toggle Secondary Constraints.

***

**Quick Start**

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Generate a grid over Seattle:**
   ```bash
   python src/grid_generator.py --boundary data/seattle_city_limits.geojson --cell 500
   ```

3. **Create a flight path with neighborhoods:**
   ```bash
   python src/neighborhood_graph.py
   ```

4. **Build an operational intent (4D volumes + KML):**
   ```bash
   python src/build_operational_intent.py --start 47.6336,-122.3572 --end 47.6311,-122.3503
   ```

5. **Open the generated KML in Google Earth:**
   - Open `output/flight_volumes.kml` in Google Earth
   - Visualize waypoints, volumes, and time-based annotations

***

**Project Structure**

```
UTM-orchestrator/
├── src/                          # Python source code
│   ├── grid_generator.py         # Geographic grid creation
│   ├── poi_generator.py          # Points of Interest generation
│   ├── flight_generator.py       # Synthetic flight mission creation
│   ├── neighborhood_graph.py     # Pathfinding (A* / BFS)
│   ├── waypoint_engine.py        # Waypoint generation (TBD)
│   ├── volumizer.py              # 4D volume creation
│   ├── kml_exporter.py           # KML export (TBD)
│   ├── build_operational_intent.py # End-to-end orchestrator (TBD)
│   ├── obstacle_loader.py        # Obstacle data loading
│   ├── obstacle_preprocess.py    # FAA DOF processing
│   ├── notam_fetch.py            # NOTAM integration (future)
│   ├── notam_constraints.py      # NOTAM constraint handling (future)
│   ├── visualizer.py             # Map visualization
│   └── run_notams.py             # NOTAM orchestration (future)
├── data/                         # Geospatial data
│   ├── points_of_interest.csv
│   ├── points_of_interest.geojson
│   ├── seattle_city_limits.geojson
│   ├── airspace/                 # Airspace constraint layers
│   ├── obstacles/                # Obstacle data
│   └── tiles_sectional/          # Map tiles
├── output/                       # Generated outputs
├── community_notes/              # Community contributions
├── OPERATIONAL_INTENT_PLAN.md    # Development plan
├── requirements.txt              # Python dependencies
└── README.md                     # This file
```

***

**Dependencies**

Key Python libraries:
- `geopandas` – Geospatial data handling
- `shapely` – Geometric operations
- `folium` – Interactive map visualization
- `pyproj` – Coordinate reference system transformations
- `pandas` – Data manipulation
- `gpxpy` – GPX file handling
- `simplekml` – KML export (to be added)

See `requirements.txt` for the full list.

***

**Contributing**

Contributions are welcome! Please add ideas, suggestions, or discussions to:
```
UTM-orchestrator/community_notes
```

This project thrives on community input to explore real UTM challenges and solutions.

***

**License**

See LICENSE file for details.

***

**References**

- ASTM F3548-21: Standard Practice for Design of an Airborne Detect and Avoid System
- FAA UTM Implementation: https://www.faa.gov/uas/research_development/traffic_management/
- U-Space Concept: https://www.eurocontrol.int/u-space
- OpenAirspace: https://openairspace.org

