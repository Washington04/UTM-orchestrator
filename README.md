**UTM Orchestrator**

_A lightweight, standards-aligned UAS Traffic Management (UTM) simulation environment_

Note: UTM Orchestrator is a learning project to explore UTM technical challenges, geospatial approaches, and airspace interoperability. Contributions, suggestions, and discussions are welcome. Please add them to UTM-orchestrator/community_notes. 

***

**Overview**

**UTM Orchestrator** is a developing simulation framework designed to model a full UAS Traffic Management (UTM) ecosystem in the Seattle metropolitan area.

The system generates:
- Geographical operating areas
- Operational intents (merchant → customer → hub)
- Static & dynamic constraints
- POIs and route generation
- Basic strategic deconfliction workflows

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

**Geospatial Grid Generation**
- Generates a meter-accurate grid over Seattle using:
  - Dynamic UTM projection
  - Polygon clipping
  - Unique cell_ids
  - Rounded centroid coordinates
- Outputs clean GeoJSON for UTM-style visualization

**Points of Interest (POI) System**
- Generates synthetic:
  - hub locations
  - merchant pickup sites
  - customer delivery points
- Outputs both CSV and GeoJSON for visual overlays

**Visualization Support**
- Native preview inside VS Code
- Layered visualization using GeoJSON standards
- Supports grid + POI overlays for operational alignment

***

**In Development (Roadmap)**

**Flight Generator** 
- Create realistic delivery missions:
  - hub → merchant → customer → hub
- Associate each flight with grid cells + coordinates
- Output per-flight operational intent objects

**Strategic Coordination Simulation**
- Identify conflicts using:
  - Spatial overlap
  - Time windows
  - Prioritization rules
- Apply “US Shared Airspace” guiding principles

**Constraint Modeling**
- Add:
  - No-fly zones / Special Use Airspace
  - Temporary flight restrictions
  - Weather constraints

***

**Long-Term** 
- UTM Orchestrator aims to serve as a sandbox environment for:
  - Exploring tradeoffs in UTM decisions
  - Strategic coordination testing
  - Rapid prototyping of UTM concepts

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

{
  "name_snake": "identifier_in_snake_case",
  "altitude": 400,
  "priority": "high"
}


- name_snake: short identifier in snake_case
- altitude: integer altitude limit (feet)
- priority: "low", "medium", or "high"=
- Coordinates must be standard GeoJSON:
 - [longitude, latitude]
 - CRS: EPSG:4326

**Polygon Example**
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

**Corridor Example (auto-buffered 30m)**
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

**Updating Secondary Constraints**

Edit the GeoJSON file:
data/airspace/processed/secondary_constraints_seattle.geojson

Add, modify, or delete a Feature.

Run:
python src/visualizer.py


Open the most recently generated map in output/ and toggle Secondary Constraints.


