# TrafficWatch

**Local traffic-camera change detection for Waze editors.** Point it at public traffic-camera still images, draw a box around each direction of travel, and get a Discord or Pushover alert (with before/after images) when that direction's traffic changes:

- **Closure lifted:** a direction that's been empty for several scans suddenly has vehicles.
- **Incident cleared:** traffic that was stopped is moving again.
- **New incident:** moving traffic comes to a standstill, or a busy direction goes empty.
- **Heavy traffic:** vehicle count crosses a threshold.

Everything runs on your own computer in one Docker container. Vehicle detection uses local YOLO models through ONNX Runtime, with **no cloud AI and no API keys**. All configuration happens in the web UI: cameras, zones, rules, Discord, Pushover and detector settings. No environment variables or config files.

## Quick start

```bash
git clone https://github.com/SecuredUnderscore/Traffic-Webcam-Monitor.git
cd Traffic-Webcam-Monitor
docker compose up -d --build
```

Open **http://localhost:8080**. The first build takes a few minutes because it downloads and converts the detection models. Data (database, scan images) lives in the `trafficwatch-data` Docker volume.

1. **Add camera**: paste the image URL (e.g. `https://images.wsdot.wa.gov/nw/405vc00229.jpg`), press **Test**, then pick how often to check.
2. **Draw zones** on the camera page with **Box** or **Polygon**, one per direction (NB lanes, SB lanes…), or press **Auto-detect lanes**.
3. **Add rules** to a zone from presets (*Traffic returns*, *Starts moving*, *Becomes stopped*, *Goes empty*, *Heavy traffic*) or build your own.
4. **Settings**: paste a Discord webhook and/or Pushover keys, then press **Send test**.

## How it works with 5–20 minute images

There's no video, so nothing can be tracked frame-to-frame. Instead, every new image is compared against what the camera *remembers* from earlier scans:

| Signal | What it measures | Used for |
|---|---|---|
| **Vehicles** | Detections whose road contact point lies inside the zone | Traffic level (empty / light / moderate / heavy) |
| **Stationary** | Share of vehicles in the *same spot, looking the same* as in the previous scan minutes ago | Flow: stopped (≥60%) / slow (30–60%) / moving |
| **Activity** | % of the zone that differs from the learned empty road (median of recent scans) | Traffic level when vehicles are too small to detect |
| **Change** | % of the zone that changed since the previous scan | Pixel-based flow when vehicles are too small |
| **View check** | Edge similarity with the previous scan, ignoring vehicles | Detects a PTZ camera being panned or zoomed and pauses alerts |

Rules look at the **sequence** of scans ("empty for ≥ 2 scans, then light/moderate/heavy, confirmed for 1 scan"). Scans where a state can't be determined are skipped instead of breaking the sequence, and each rule has a cooldown.

Other details handled:
- **Unchanged images** are skipped, using `ETag`/`Last-Modified` plus a content hash.
- **Half-written images** are retried a few seconds later. Some DOT servers serve all-zero files mid-update.
- **Night direction hint**: red taillights mean traffic heading away from the camera; white headlights mean traffic heading toward it.

## Do I need a GPU?

**No.** Measured on a Ryzen 9 9900X with real 335×244 WSDOT frames (median per frame):

| Model | CPU full frame | CPU 2×2 tiles | RTX 5070 full | RTX 5070 2×2 tiles |
|---|---:|---:|---:|---:|
| yolo11n | 20 ms | 99 ms | 10 ms | 29 ms |
| yolo11s *(default)* | 35 ms | 181 ms | 8 ms | 40 ms |
| yolo11m | 76 ms | 380 ms | 9 ms | 48 ms |
| yolo26n | 18 ms | 94 ms | 8 ms | 33 ms |
| yolo26s | 41 ms | 185 ms | 7 ms | 45 ms |
| yolo26m | 73 ms | 357 ms | 15 ms | 50 ms |

A camera that updates every 5 minutes needs one detection per 5 minutes. Even 50 cameras with 2×2 tiling on `yolo11s` need **about 2 seconds of processing per minute**. Any recent 4+ core CPU (or an Apple Silicon or Intel N100-class mini PC) is plenty, and RAM use is around 300–500 MB. A GPU only matters if you want the largest models with fine tiling on many dozens of cameras, or if you later add a local vision-language model.

Use **Detector Lab** in the UI to run this comparison on your own cameras and hardware.

### Accuracy notes (what the Lab showed)

- **Tiling helps a lot on small images.** On the I-405 @ SR 167 cam, `yolo11n` found 14 vehicles on the full frame and 20 with 2×2 tiles. 2×2 tiling is the default.
- **Bigger isn't always better here.** The `s` models were the best balance; `m` models were slower without finding more vehicles on these low-res frames.
- **Very distant vehicles (under ~10 px) are invisible to every model**, even upscaled. On the I-90 floating-bridge cam, every model scored 0 although cars are visible. For zones like that, switch the zone's metric to **Pixel activity**, which detects traffic without recognizing individual vehicles.
- **Night and glare** reduce detection. Activity and the light-colour hint keep working at night.

### Optional: GPU build

Requires an NVIDIA GPU with a recent driver (CUDA 13), plus the NVIDIA Container Toolkit on Linux or Docker Desktop with WSL2 on Windows.

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Then choose **NVIDIA GPU (CUDA)** in Settings → Vehicle detection. The GPU image is about 3 GB larger.

### Custom models

Drop any Ultralytics-format YOLO detection model exported to ONNX (`yolo export format=onnx`) into `/data/models/` inside the volume and it appears in the model lists. It must use COCO class ids for car/motorcycle/bus/truck. A model fine-tuned on traffic-camera imagery (e.g. UA-DETRAC or VisDrone) can improve small-vehicle detection.

## Development

```bash
# Backend (Python 3.12)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
docker build --target models -t tw-models .. && docker run --rm -v $PWD/models:/out tw-models cp -r /models/. /out/
TW_DATA_DIR=./data TW_MODELS_DIR=./models .venv/bin/uvicorn app.main:app --reload --port 8080
.venv/bin/python -m pytest tests

# Frontend (Node 20+)
cd frontend && npm install && npm run dev   # http://localhost:5173, proxies /api to :8080
```

Layout:

```
backend/app/
  detector.py   ONNX YOLO inference, tiling, model registry
  analysis.py   per-zone signals and states, camera memory, view-shift check
  rules.py      sequence-based alert rules
  monitor.py    scheduler, fetch → detect → analyze → rules → notify, retention
  autozones.py  lane suggestions from detection heatmaps
  notify.py     Discord webhook (multi-image) and Pushover
  api/          REST API used by the UI
frontend/src/   React + TypeScript UI (zone editor, dashboard, alerts, lab, settings)
```

## Licensing note

The bundled YOLO11/YOLO26 weights are from Ultralytics and licensed **AGPL-3.0**. That's fine for personal and community use. For closed-source redistribution, swap in an Apache-licensed detector via `/data/models`.
