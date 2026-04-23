#!/usr/bin/env python3
"""
KML Exporter: Convert 4D volumes to KML for Google Earth visualization.

All styles are defined at <Document> level so Google Earth resolves them
reliably. Each segment volume is a closed 3D box (ceiling + floor + walls).

Usage:
    python src/kml_exporter.py --volumes output/volumes.geojson
    python src/kml_exporter.py --volumes output/volumes.geojson \
        --waypoints output/waypoints.json --output output/flight_volumes.kml
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET
from xml.dom import minidom

ROOT = Path(__file__).resolve().parent.parent
FT_TO_M = 0.3048

KML_NS = "http://www.opengis.net/kml/2.2"
GX_NS  = "http://www.google.com/kml/ext/2.2"
ET.register_namespace("",   KML_NS)
ET.register_namespace("gx", GX_NS)

# Shared style IDs — defined once at <Document> level
_SID_VOL        = "vol_style"
_SID_CYL_ORIG   = "cyl_orig_style"
_SID_CYL_DEST   = "cyl_dest_style"
_SID_CONFLICT   = "conflict_style"
_SID_ROUTE      = "route_style"
_SID_ORIG       = "origin_style"
_SID_DEST       = "dest_style"
_SID_WP         = "wp_style"

# KML colors: AABBGGRR
_VOL_LINE       = "ff00c8ff"
_VOL_FILL       = "4f00c8ff"
_CYL_ORIG_LINE  = "ff00c8ff"
_CYL_ORIG_FILL  = "4f00c8ff"
_CYL_DEST_LINE  = "ff00c8ff"
_CYL_DEST_FILL  = "4f00c8ff"
_CONFLICT_LINE  = "ff0000ff"   # red
_CONFLICT_FILL  = "660000ff"   # semi-transparent red
_ROUTE_CLR      = "ff44ff00"
_ORIG_CLR       = "ff00cc00"
_DEST_CLR       = "ff0000ff"
_WP_CLR         = "ffffffff"


# ── XML helpers ───────────────────────────────────────────────────────────────

def _t(name: str) -> str:
    return f"{{{KML_NS}}}{name}"


def _sub(parent: ET.Element, tag: str, text: str = None, **attrib) -> ET.Element:
    el = ET.SubElement(parent, _t(tag), attrib)
    if text is not None:
        el.text = text
    return el


# ── Shared styles ─────────────────────────────────────────────────────────────

def _add_styles(doc: ET.Element) -> None:
    def style(sid): return ET.SubElement(doc, _t("Style"), id=sid)
    def ls(s, color, width="1"):
        n = ET.SubElement(s, _t("LineStyle"))
        ET.SubElement(n, _t("color")).text = color
        ET.SubElement(n, _t("width")).text = width
    def ps(s, color):
        n = ET.SubElement(s, _t("PolyStyle"))
        ET.SubElement(n, _t("color")).text = color
        ET.SubElement(n, _t("fill")).text = "1"
        ET.SubElement(n, _t("outline")).text = "1"
    def ic(s, color, scale="1", href=None):
        n = ET.SubElement(s, _t("IconStyle"))
        ET.SubElement(n, _t("color")).text = color
        ET.SubElement(n, _t("scale")).text = scale
        if href:
            icon = ET.SubElement(n, _t("Icon"))
            ET.SubElement(icon, _t("href")).text = href

    s = style(_SID_VOL);       ls(s, _VOL_LINE);       ps(s, _VOL_FILL)
    s = style(_SID_CYL_ORIG);  ls(s, _CYL_ORIG_LINE);  ps(s, _CYL_ORIG_FILL)
    s = style(_SID_CYL_DEST);  ls(s, _CYL_DEST_LINE);  ps(s, _CYL_DEST_FILL)
    s = style(_SID_CONFLICT);  ls(s, _CONFLICT_LINE);   ps(s, _CONFLICT_FILL)
    s = style(_SID_ROUTE);  ls(s, _ROUTE_CLR, "3")
    s = style(_SID_ORIG);   ic(s, _ORIG_CLR,
        href="http://maps.google.com/mapfiles/kml/paddle/grn-circle.png")
    s = style(_SID_DEST);   ic(s, _DEST_CLR,
        href="http://maps.google.com/mapfiles/kml/paddle/red-stars.png")
    s = style(_SID_WP);     ic(s, _WP_CLR, scale="0.6",
        href="http://maps.google.com/mapfiles/kml/shapes/donut.png")


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _polygon_pm(parent: ET.Element, name: str, coords_3d,
                style_id: str, desc: str) -> None:
    pm = _sub(parent, "Placemark")
    _sub(pm, "name", name)
    if desc:
        _sub(pm, "description", desc)
    _sub(pm, "styleUrl", f"#{style_id}")
    pol = _sub(pm, "Polygon")
    _sub(pol, "altitudeMode", "relativeToGround")
    ob = _sub(pol, "outerBoundaryIs")
    lr = _sub(ob, "LinearRing")
    _sub(lr, "coordinates",
         " ".join(f"{lon},{lat},{alt:.3f}" for lon, lat, alt in coords_3d))


# ── Folders ───────────────────────────────────────────────────────────────────

def _volumes_folder(doc: ET.Element, features: List[Dict],
                    conflicting_indices: set = None) -> None:
    folder = _sub(doc, "Folder")
    _sub(folder, "name", "4D Volumes")

    for feat_idx, feat in enumerate(features):
        p         = feat["properties"]
        vtype     = p.get("volume_type", "segment")
        min_m     = p["min_alt_ft"] * FT_TO_M
        max_m     = p["max_alt_ft"] * FT_TO_M
        tb        = _kml_time(p["start_time"])
        te        = _kml_time(p["end_time"])
        ring      = feat["geometry"]["coordinates"][0]

        is_conflict = conflicting_indices and feat_idx in conflicting_indices

        if vtype == "origin":
            folder_name = "Origin Cylinder"
            sid = _SID_CONFLICT if is_conflict else _SID_CYL_ORIG
            desc = (
                f"Origin takeoff envelope\n"
                f"Altitude: {p['min_alt_ft']:.0f} - {p['max_alt_ft']:.0f} ft AGL\n"
                f"Start: {tb}\nEnd: {te}"
            )
        elif vtype == "destination":
            folder_name = "Destination Cylinder"
            sid = _SID_CONFLICT if is_conflict else _SID_CYL_DEST
            desc = (
                f"Destination landing envelope\n"
                f"Altitude: {p['min_alt_ft']:.0f} - {p['max_alt_ft']:.0f} ft AGL\n"
                f"Start: {tb}\nEnd: {te}"
            )
        else:
            seg = p["segment_index"]
            folder_name = f"Segment {seg}"
            sid = _SID_CONFLICT if is_conflict else _SID_VOL
            desc = (
                f"Segment: {seg}\n"
                f"Altitude: {p['min_alt_ft']:.0f} - {p['max_alt_ft']:.0f} ft AGL\n"
                f"Start:    {tb}\nEnd:      {te}\nDuration: {p['duration_s']:.1f} s"
            )

        sf = _sub(folder, "Folder")
        _sub(sf, "name", folder_name)

        _polygon_pm(sf, "ceiling", [(lon, lat, max_m) for lon, lat in ring],
                    sid, desc)
        _polygon_pm(sf, "floor",   [(lon, lat, min_m) for lon, lat in ring],
                    sid, desc)

        for i in range(len(ring) - 1):
            lon0, lat0 = ring[i]
            lon1, lat1 = ring[i + 1]
            _polygon_pm(sf, f"wall {i}", [
                (lon0, lat0, min_m), (lon1, lat1, min_m),
                (lon1, lat1, max_m), (lon0, lat0, max_m),
                (lon0, lat0, min_m),
            ], sid, "")


def _route_folder(doc: ET.Element, waypoints: List[Dict]) -> None:
    folder = _sub(doc, "Folder")
    _sub(folder, "name", "Route")
    alt_m = waypoints[0]["alt_agl"] * FT_TO_M

    # Route polyline subfolder
    line_folder = _sub(folder, "Folder")
    _sub(line_folder, "name", "Route Line")
    pm = _sub(line_folder, "Placemark")
    _sub(pm, "name", "A* Route")
    _sub(pm, "styleUrl", f"#{_SID_ROUTE}")
    ls = _sub(pm, "LineString")
    _sub(ls, "altitudeMode", "relativeToGround")
    _sub(ls, "coordinates",
         " ".join(f"{w['lon']},{w['lat']},{alt_m:.3f}" for w in waypoints))

    # Waypoint pins subfolder
    wp_folder = _sub(folder, "Folder")
    _sub(wp_folder, "name", "Waypoints")
    for w in waypoints:
        step      = w["step"]
        is_origin = step == 0
        is_dest   = step == len(waypoints) - 1
        label     = "Origin" if is_origin else "Destination" if is_dest else f"WP {step}"
        sid       = _SID_ORIG if is_origin else _SID_DEST if is_dest else _SID_WP

        pm = _sub(wp_folder, "Placemark")
        _sub(pm, "name", label)
        _sub(pm, "description",
             f"Step: {step}\nLat:  {w['lat']}\nLon:  {w['lon']}\n"
             f"Alt:  {w['alt_agl']} ft AGL\nTime: {w['time']}\n"
             f"Dist: {w['cumulative_distance_m']} m")
        _sub(pm, "styleUrl", f"#{sid}")
        pt = _sub(pm, "Point")
        _sub(pt, "altitudeMode", "relativeToGround")
        _sub(pt, "coordinates", f"{w['lon']},{w['lat']},{alt_m:.3f}")


# ── Build ─────────────────────────────────────────────────────────────────────

def build_kml(features: List[Dict], waypoints: Optional[List[Dict]] = None,
              conflicting_indices: set = None) -> str:
    kml_el = ET.Element(_t("kml"))
    doc    = _sub(kml_el, "Document")
    _sub(doc, "name", "UTM Operational Intent")

    _add_styles(doc)
    _volumes_folder(doc, features, conflicting_indices)
    if waypoints:
        _route_folder(doc, waypoints)

    rough    = ET.tostring(kml_el, encoding="unicode")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="    ")


def build_combined_kml(
    flights: List[Dict],  # list of {id, features, waypoints (optional), conflicting_indices}
) -> str:
    """Build a single KML with one top-level Folder per flight."""
    kml_el = ET.Element(_t("kml"))
    doc    = _sub(kml_el, "Document")
    _sub(doc, "name", "UTM Operational Intent — All Flights")

    _add_styles(doc)

    for flight in flights:
        fid         = flight["id"]
        features    = flight["features"]
        waypoints   = flight.get("waypoints")
        conflicting = flight.get("conflicting_indices", set())

        flight_folder = _sub(doc, "Folder")
        _sub(flight_folder, "name", fid)

        _volumes_folder(flight_folder, features, conflicting)
        if waypoints:
            _route_folder(flight_folder, waypoints)

    rough    = ET.tostring(kml_el, encoding="unicode")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="    ")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _kml_time(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_volumes(path: Path) -> List[Dict]:
    with open(path) as f:
        return json.load(f)["features"]


def _load_waypoints(path: Path) -> List[Dict]:
    with open(path) as f:
        data = json.load(f)
    return data["waypoints"] if "waypoints" in data else data


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export 4D volumes to KML for Google Earth.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--volumes",   required=True, metavar="PATH",
                        help="Volumes GeoJSON from volumizer.py")
    parser.add_argument("--waypoints", metavar="PATH",
                        help="Waypoints JSON from waypoint_engine.py (adds route layer)")
    parser.add_argument("--output",    default=None, metavar="PATH",
                        help="Output KML path (default: output/flight_volumes_YYYYMMDD_HHMMSS.kml)")
    args = parser.parse_args()

    vol_path = Path(args.volumes)
    if not vol_path.is_absolute():
        vol_path = ROOT / vol_path
    features = _load_volumes(vol_path)

    waypoints = None
    if args.waypoints:
        wp_path = Path(args.waypoints)
        if not wp_path.is_absolute():
            wp_path = ROOT / wp_path
        waypoints = _load_waypoints(wp_path)

    xml_str  = build_kml(features, waypoints)
    if args.output:
        out_path = ROOT / args.output
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = ROOT / "output" / f"flight_volumes_{ts}.kml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xml_str)

    print(f"Segments: {len(features)}")
    print(f"KML:      {out_path}")
