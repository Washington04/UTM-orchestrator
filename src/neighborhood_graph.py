from pathlib import Path
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

Node = Tuple[int, int]

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
import folium
import heapq
import math

# --------------------
# Paths / CRS
# --------------------

ROOT = Path(__file__).resolve().parent.parent

AOI_FILE = ROOT / "data" / "airspace" / "processed" / "queen_anne_aoi.geojson"
OBSTACLE_FILE = ROOT / "data" / "obstacles" / "faa_dof_queen_anne.geojson"
OUT_HTML = ROOT / "output" / "queen_anne_bfs.html"

CRS_WGS84 = "EPSG:4326"
CRS_METERS = "EPSG:26910"  # Seattle UTM
SPACING_M = 30

# 8-neighbor deltas (row, col)
DELTAS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    ( 0, -1),          ( 0, 1),
    ( 1, -1), ( 1, 0), ( 1, 1),
]

Node = Tuple[int, int]  # (r, c)


# --------------------
# Loaders
# --------------------

def load_aoi_m() -> gpd.GeoSeries:
    aoi = gpd.read_file(AOI_FILE)
    if aoi.crs is None:
        aoi = aoi.set_crs(CRS_WGS84)
    return aoi.to_crs(CRS_METERS).geometry


def load_obstacles_m() -> gpd.GeoDataFrame:
    if not OBSTACLE_FILE.exists():
        return gpd.GeoDataFrame(geometry=[], crs=CRS_METERS)
    obs = gpd.read_file(OBSTACLE_FILE)
    if obs.crs is None:
        obs = obs.set_crs(CRS_WGS84)
    return obs.to_crs(CRS_METERS)


# --------------------
# Graph build
# --------------------

def build_nodes(aoi_geom, spacing_m: int) -> gpd.GeoDataFrame:
    minx, miny, maxx, maxy = aoi_geom.bounds
    xs = np.arange(minx, maxx + spacing_m, spacing_m)
    ys = np.arange(miny, maxy + spacing_m, spacing_m)

    rows, cols, geoms = [], [], []
    for r, y in enumerate(ys):
        for c, x in enumerate(xs):
            p = Point(float(x), float(y))
            if aoi_geom.contains(p):
                rows.append(r)
                cols.append(c)
                geoms.append(p)

    return gpd.GeoDataFrame(
        {"r": rows, "c": cols},
        geometry=geoms,
        crs=CRS_METERS,
    )


def mask_blocked(nodes: gpd.GeoDataFrame, obstacles: gpd.GeoDataFrame) -> Tuple[Set[Node], Set[Node]]:
    all_nodes = {(int(r), int(c)) for r, c in zip(nodes["r"], nodes["c"])}
    if obstacles.empty:
        return all_nodes, set()

    joined = gpd.sjoin(nodes, obstacles[["geometry"]], predicate="within", how="left")
    blocked = {
        (int(r), int(c))
        for r, c, hit in zip(joined["r"], joined["c"], joined["index_right"].notna())
        if hit
    }
    valid = all_nodes - blocked
    return valid, blocked


def neighbors_8(n: Node, valid: Set[Node]):
    r, c = n
    for dr, dc in DELTAS_8:
        nb = (r + dr, c + dc)
        if nb in valid:
            yield nb


# --------------------
# BFS
# --------------------

def bfs(start: Node, goal: Node, valid: Set[Node]) -> Optional[List[Node]]:
    if start not in valid or goal not in valid:
        return None

    q = deque([start])
    came = {start: None}

    while q:
        cur = q.popleft()
        if cur == goal:
            break
        for nb in neighbors_8(cur, valid):
            if nb not in came:
                came[nb] = cur
                q.append(nb)

    if goal not in came:
        return None

    path = []
    cur = goal
    while cur is not None:
        path.append(cur)
        cur = came[cur]
    return list(reversed(path))

# --------------------
# A*
# --------------------

def astar(start: Node, goal: Node, valid: Set[Node]) -> Optional[List[Node]]:
    """
    A* on an 8-connected grid where straight moves cost 1 and diagonal moves cost sqrt(2).
    Uses Euclidean distance in grid space as the heuristic.
    """
    if start not in valid or goal not in valid:
        return None

    def move_cost(a: Node, b: Node) -> float:
        dr = abs(a[0] - b[0])
        dc = abs(a[1] - b[1])
        # 8-neighbor implies (dr,dc) is one of: (1,0), (0,1), (1,1)
        return math.sqrt(2) if (dr == 1 and dc == 1) else 1.0

    def heuristic(n: Node) -> float:
        # Euclidean distance in grid coordinates (admissible with the costs above)
        return math.hypot(goal[0] - n[0], goal[1] - n[1])

    open_heap: List[Tuple[float, float, Node]] = []
    heapq.heappush(open_heap, (heuristic(start), 0.0, start))

    came: Dict[Node, Optional[Node]] = {start: None}
    g_score: Dict[Node, float] = {start: 0.0}

    while open_heap:
        f, g, cur = heapq.heappop(open_heap)

        if cur == goal:
            # reconstruct
            path: List[Node] = []
            n: Optional[Node] = goal
            while n is not None:
                path.append(n)
                n = came[n]
            return list(reversed(path))

        # If we popped a stale (worse) entry, skip it
        if g > g_score.get(cur, float("inf")):
            continue

        for nb in neighbors_8(cur, valid):
            tentative_g = g_score[cur] + move_cost(cur, nb)
            if tentative_g < g_score.get(nb, float("inf")):
                came[nb] = cur
                g_score[nb] = tentative_g
                heapq.heappush(open_heap, (tentative_g + heuristic(nb), tentative_g, nb))

    return None

# --------------------
# Snapping
# --------------------

def snap_latlon_to_node(lat: float, lon: float, nodes_xy: Dict[Node, Point], valid: Set[Node]) -> Node:
    p = gpd.GeoDataFrame(
        geometry=[Point(lon, lat)], crs=CRS_WGS84
    ).to_crs(CRS_METERS).geometry.iloc[0]

    best = None
    best_d2 = float("inf")
    for n, pt in nodes_xy.items():
        if n not in valid:
            continue
        d2 = (pt.x - p.x) ** 2 + (pt.y - p.y) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best = n
    if best is None:
        raise RuntimeError("No valid node to snap to")
    return best


def to_latlon(points_m: List[Point]) -> List[Tuple[float, float]]:
    gdf = gpd.GeoDataFrame(geometry=points_m, crs=CRS_METERS).to_crs(CRS_WGS84)
    return [(p.y, p.x) for p in gdf.geometry]


# --------------------
# Visualization
# --------------------

def visualize(
    aoi_wgs84,
    obstacles_wgs84,
    nodes_xy: Dict[Node, Point],
    valid: Set[Node],
    blocked: Set[Node],
    path: Optional[List[Node]],
):
    centroid = aoi_wgs84.geometry.iloc[0].centroid
    m = folium.Map(location=[centroid.y, centroid.x], zoom_start=15, tiles="CartoDB positron")

    # Google Satellite
    folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google",
    name="Google Satellite",
    overlay=False,
    control=True,
    show=False,
    ).add_to(m)

    # Optional: Hybrid label
    folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    attr="Google",
    name="Google Hybrid (labels)",
    overlay=False,
    control=True,
    show=False,
    ).add_to(m)

    # AOI
    aoi_coords = list(aoi_wgs84.geometry.iloc[0].exterior.coords)
    folium.Polygon(
        locations=[[lat, lon] for lon, lat in aoi_coords],
        color="blue",
        weight=2,
        fill=False,
        tooltip="Queen Anne AOI",
    ).add_to(m)

    # Obstacles
    obs_layer = folium.FeatureGroup(name="Obstacles", show=True)
    for g in obstacles_wgs84.geometry:
        coords = list(g.exterior.coords)
        folium.Polygon(
            locations=[[lat, lon] for lon, lat in coords],
            weight=1,
            fill=True,
            fill_opacity=0.2,
            tooltip="Obstacle buffer",
        ).add_to(obs_layer)
    obs_layer.add_to(m)

    # Nodes (sampled so map stays fast)
    free_layer = folium.FeatureGroup(name="Nodes (free)", show=False)
    blocked_layer = folium.FeatureGroup(name="Nodes (blocked)", show=False)

    SAMPLE = 4  # set to 1 if you want to see every node
    for i, (n, pt) in enumerate(nodes_xy.items()):
        if i % SAMPLE != 0:
            continue
        latlon = to_latlon([pt])[0]
        if n in blocked:
            folium.CircleMarker(
                location=latlon,
                radius=1,
                opacity=0.9,
                fill=True,
                fill_opacity=0.9,
                tooltip="blocked",
            ).add_to(blocked_layer)
        else:
            folium.CircleMarker(
                location=latlon,
                radius=1,
                opacity=0.5,
                fill=True,
                fill_opacity=0.5,
                tooltip="free",
            ).add_to(free_layer)

    # add node layers once
    free_layer.add_to(m)
    blocked_layer.add_to(m)

    # Path (draw both the polyline AND the exact nodes used)
    if path is not None and len(path) > 0:
        path_layer = folium.FeatureGroup(name="Path (polyline)", show=True)
        path_nodes_layer = folium.FeatureGroup(name="Path nodes (exact)", show=True)
        edges_layer = folium.FeatureGroup(name="Path edges (segments)", show=False)

        pts_m = [nodes_xy[n] for n in path]
        pts_ll = to_latlon(pts_m)

        # polyline
        folium.PolyLine(pts_ll, color="red", weight=4).add_to(path_layer)

        # nodes used by path (highlight every node)
        for i, (lat, lon) in enumerate(pts_ll):
            folium.CircleMarker(
                location=(lat, lon),
                radius=3,
                weight=2,
                opacity=1.0,
                fill=True,
                fill_opacity=1.0,
                tooltip=f"step={i}",
            ).add_to(path_nodes_layer)

        # edges (segment-by-segment between consecutive path nodes)
        for (a, b) in zip(pts_ll[:-1], pts_ll[1:]):
            folium.PolyLine([a, b], weight=6, opacity=0.5).add_to(edges_layer)

        # add layers to map
        path_layer.add_to(m)
        path_nodes_layer.add_to(m)
        edges_layer.add_to(m)

    # controls + save
    folium.LayerControl().add_to(m)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    m.save(OUT_HTML)
    print(f"Saved {OUT_HTML}")


# --------------------
# Main (example run)
# --------------------

if __name__ == "__main__":
    aoi_m = load_aoi_m().iloc[0]
    obs_m = load_obstacles_m()

    nodes_gdf = build_nodes(aoi_m, SPACING_M)
    valid, blocked = mask_blocked(nodes_gdf, obs_m)

    nodes_xy = {
        (int(r), int(c)): geom
        for r, c, geom in zip(nodes_gdf["r"], nodes_gdf["c"], nodes_gdf.geometry)
    }

    # Example start/goal inside QA (you can replace with POIs later)
    start_ll = (47.6336, -122.3572)
    goal_ll  = (47.6311, -122.3503)

    start = snap_latlon_to_node(*start_ll, nodes_xy, valid)
    goal  = snap_latlon_to_node(*goal_ll,  nodes_xy, valid)

    print("ROUTER = A*")
    path = astar(start, goal, valid)

    aoi_wgs = gpd.read_file(AOI_FILE)
    if aoi_wgs.crs is None:
        aoi_wgs = aoi_wgs.set_crs(CRS_WGS84)

    obs_wgs = gpd.read_file(OBSTACLE_FILE)
    if obs_wgs.crs is None:
        obs_wgs = obs_wgs.set_crs(CRS_WGS84)

    visualize(aoi_wgs, obs_wgs, nodes_xy, valid, blocked, path)
