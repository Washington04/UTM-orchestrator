"""
notam_constraints.py

Turn NOTAM GeoJSON (or FAA-style NOTAM responses that contain GeoJSON) into
operational constraint layers (FeatureCollections) that your UTM Orchestrator
can visualize and use for conflict detection/path planning.

This module intentionally separates:
- classification (what kind of NOTAM is it?)
- geometry extraction/normalization (what is the shape?)
- property extraction (what metadata do we keep?)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------
# Types (lightweight / practical)
# -----------------------------

GeoJSON = Dict[str, Any]
Feature = Dict[str, Any]
FeatureCollection = Dict[str, Any]


@dataclass(frozen=True)
class ParsedNotamTimeWindow:
    start_utc: Optional[datetime]
    end_utc: Optional[datetime]


# -----------------------------
# Public API
# -----------------------------

def extract_notam_constraints(notam_response: Dict[str, Any]) -> Dict[str, FeatureCollection]:
    """
    Convert a NOTAM response containing GeoJSON features into constraint layers.

    Returns:
        {
          "uas_airspace": FeatureCollection,
          "obstacles": FeatureCollection,
          "other": FeatureCollection
        }

    Notes:
      - This function is defensive about response shapes.
      - It does not attempt to fetch NOTAMs; it only transforms input.
    """
    features_in = _get_features_from_response(notam_response)

    uas_airspace_features: List[Feature] = []
    obstacle_features: List[Feature] = []
    other_features: List[Feature] = []

    for f in features_in:
        kind = classify_notam(f)
        geom = derive_geometry(f)
        if geom is None:
            # skip features with no usable geometry
            continue

        props = extract_properties(f)

        out_feature: Feature = {
            "type": "Feature",
            "properties": props,
            "geometry": geom,
        }

        if kind == "uas_airspace":
            uas_airspace_features.append(out_feature)
        elif kind == "obstacle":
            obstacle_features.append(out_feature)
        else:
            other_features.append(out_feature)

    return {
        "uas_airspace": _fc(uas_airspace_features),
        "obstacles": _fc(obstacle_features),
        "other": _fc(other_features),
    }


# -----------------------------
# Classification
# -----------------------------

def classify_notam(feature: Feature) -> str:
    """
    Heuristic classification.

    Returns one of:
      - "uas_airspace"
      - "obstacle"
      - "other"
    """
    props = feature.get("properties", {}) or {}

    # Common fields you might see depending on source:
    # - "notamText", "text", "description", "purpose", "type", "category"
    text = " ".join(
        str(props.get(k, "") or "")
        for k in ("notamText", "text", "description", "purpose", "type", "category", "title")
    ).upper()

    # Quick/rough keywords (you’ll tune this as you see real data)
    if any(k in text for k in ("UAS", "DRONE", "UNMANNED", "UA ", "UAV", "UTM")):
        return "uas_airspace"

    if any(k in text for k in ("OBST", "OBSTRUCTION", "CRANE", "TOWER", "WIRE", "POWERLINE")):
        return "obstacle"

    return "other"


# -----------------------------
# Geometry extraction / normalization
# -----------------------------

def derive_geometry(feature: Feature) -> Optional[GeoJSON]:
    """
    Return a GeoJSON geometry object.

    Expected input Feature shapes:
      - feature["geometry"] already GeoJSON
      - feature["properties"]["geometry"] (less common)
      - custom payloads: you can extend this to handle circles, etc.

    Returns None if geometry is missing or malformed.
    """
    geom = feature.get("geometry")
    if isinstance(geom, dict) and geom.get("type") and geom.get("coordinates") is not None:
        return geom

    props = feature.get("properties", {}) or {}
    geom2 = props.get("geometry")
    if isinstance(geom2, dict) and geom2.get("type") and geom2.get("coordinates") is not None:
        return geom2

    # If you later encounter circles like:
    # props["radius_m"], props["center"] = [lon, lat]
    # you can convert them to polygons here.

    return None


# -----------------------------
# Properties extraction
# -----------------------------

def extract_properties(feature: Feature) -> Dict[str, Any]:
    """
    Keep the useful metadata and normalize a couple of fields you’ll want later.
    """
    props_in = feature.get("properties", {}) or {}

    # Basic identifiers
    notam_id = props_in.get("id") or props_in.get("notamId") or props_in.get("identifier")
    source = props_in.get("source") or "notam"

    # Try to parse time window if present (optional)
    tw = parse_time_window(props_in)

    # Pull in text safely
    text = (
        props_in.get("notamText")
        or props_in.get("text")
        or props_in.get("description")
        or props_in.get("title")
        or ""
    )

    # Keep original props too (but avoid giant nested blobs if you want)
    out: Dict[str, Any] = {
        "notam_id": notam_id,
        "source": source,
        "text": text,
        "start_utc": tw.start_utc.isoformat().replace("+00:00", "Z") if tw.start_utc else None,
        "end_utc": tw.end_utc.isoformat().replace("+00:00", "Z") if tw.end_utc else None,
        # keep a few common fields if they exist
        "category": props_in.get("category"),
        "type": props_in.get("type"),
    }

    # If you want full passthrough:
    # out["raw_properties"] = props_in

    return out


def parse_time_window(props: Dict[str, Any]) -> ParsedNotamTimeWindow:
    """
    Best-effort parsing of start/end UTC time.

    Common patterns:
      - ISO strings like "2025-11-21T21:22:46Z"
      - fields named "start", "end", "effectiveStart", "effectiveEnd", etc.
    """
    start = _parse_dt(
        props.get("start")
        or props.get("start_utc")
        or props.get("effectiveStart")
        or props.get("effective_start")
    )
    end = _parse_dt(
        props.get("end")
        or props.get("end_utc")
        or props.get("effectiveEnd")
        or props.get("effective_end")
        or props.get("expires")
    )
    return ParsedNotamTimeWindow(start_utc=start, end_utc=end)


# -----------------------------
# Helpers
# -----------------------------

def _fc(features: List[Feature]) -> FeatureCollection:
    return {"type": "FeatureCollection", "features": features}


def _get_features_from_response(resp: Dict[str, Any]) -> List[Feature]:
    """
    Defensive extraction. Supports a few shapes:
      1) resp is already a FeatureCollection
      2) resp has {"type":"FeatureCollection","features":[...]}
      3) resp has nested data like resp["data"]["geojson"] or resp["data"]["features"]
    """
    if not isinstance(resp, dict):
        return []

    if resp.get("type") == "FeatureCollection" and isinstance(resp.get("features"), list):
        return resp["features"]

    if isinstance(resp.get("features"), list):
        return resp["features"]

    data = resp.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("geojson"), list):
            return data["geojson"]
        if isinstance(data.get("features"), list):
            return data["features"]

    return []


def _parse_dt(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        # normalize to UTC if naive
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)

    if not isinstance(val, str):
        return None

    s = val.strip()
    # accept "Z"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None
