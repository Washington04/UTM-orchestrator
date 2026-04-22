# UTM Orchestrator — Default Settings

Last updated: 2026-04-22

## neighborhood_graph.py
| Parameter | Default | Unit | Notes |
|-----------|---------|------|-------|
| `SPACING_M` | `30` | m | Grid cell size; diagonal step = 30√2 ≈ 42 m |

## waypoint_engine.py
| Parameter | Default | Unit | Notes |
|-----------|---------|------|-------|
| `altitude_ft` | `300.0` | ft AGL | Constant cruise altitude |
| `cruise_speed_mps` | `27.0` | m/s | ~60 mph cruise speed |

## volumizer.py
| Parameter | Default | Unit | Notes |
|-----------|---------|------|-------|
| `buffer_m` | `5.0` | m | Lateral half-width on each side of segment |
| `v_margin_ft` | `20.0` | ft | Altitude margin above and below cruise alt |
| `time_buffer_s` | `0.25` | s | Time padding at each end; creates temporal overlap between adjacent volumes |

## Pipeline commands (with defaults)
```bash
python src/waypoint_engine.py \
    --origin <LAT,LON> --dest <LAT,LON> \
    --altitude-ft 300 \
    --speed 27 \
    --output output/waypoints.json

python src/volumizer.py \
    --waypoints output/waypoints.json \
    --buffer 5 \
    --v-margin 20 \
    --output output/volumes.geojson

python src/kml_exporter.py \
    --volumes output/volumes.geojson \
    --waypoints output/waypoints.json \
    --output output/flight_volumes.kml
```
