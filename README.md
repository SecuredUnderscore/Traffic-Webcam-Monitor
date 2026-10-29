# Traffic Webcam Monitor

Watches public traffic-camera still images and sends a Discord or Pushover alert, with before/after pictures, when traffic in a lane you've outlined changes: a closure lifts, stopped traffic starts moving, a road goes empty, or volume gets heavy. Built for Waze editors.

Vehicle detection runs locally (YOLO via ONNX Runtime), with no cloud AI and no API keys. Everything is set up in the web UI.

## Run it

```bash
docker run -d --name traffic-webcam-monitor -p 8080:8080 \
  -v traffic-webcam-monitor-data:/data --restart unless-stopped \
  jaxonbjornson/traffic-webcam-monitor:latest
```

Open **http://localhost:8080**. To update, `docker pull` the image and run the command again; your data stays in the volume.

**Railway:** choose **New → Docker Image** with `jaxonbjornson/traffic-webcam-monitor:latest`, attach a volume at **`/data`** (otherwise data is wiped on redeploy), then **Generate Domain**. The app listens on Railway's `PORT`. Any other container host works the same way.

## Getting started

1. **Add a camera:** paste a still-image URL (e.g. `https://images.wsdot.wa.gov/nw/405vc00229.jpg`).
2. **Draw zones:** one per direction of travel, or press **Auto-detect lanes**.
3. **Add rules** from presets: *Traffic returns*, *Starts moving*, *Becomes stopped*, *Goes empty*, *Heavy traffic*.
4. **Settings:** add a Discord webhook and/or Pushover keys, then press **Send test**.

Each new image is compared with earlier scans: vehicles counted in each zone, how many are in the same spot as last time (stopped vs. moving), and how much of the zone differs from the empty road (for vehicles too small to detect). Unchanged images are skipped.

## Storage limit

Everything the app saves counts toward **Maximum storage** (default **400 MB**, set in **Settings → Storage** or with `TW_STORAGE_LIMIT_MB`). When it's full, the oldest scan images are deleted first, then the oldest alerts. Each camera's latest image is always kept. Set it a little below your disk or volume size.

## Hardware

No GPU needed. One detection takes about 20–200 ms on a modern CPU, and RAM use is 300–500 MB. Compare models on your own cameras in **Detector Lab**. For an NVIDIA GPU build: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`. To add your own model, put a YOLO ONNX file in `/data/models/`.

## Development

```bash
docker compose up -d --build                   # build the image from source
cd backend && python -m pytest tests            # needs TW_MODELS_DIR pointing at exported models
cd frontend && npm install && npm run dev       # UI on :5173, proxies /api to :8080
```

Backend: FastAPI + SQLite in `backend/app`. Frontend: React + TypeScript in `frontend/src`.

## License

The bundled YOLO11/YOLO26 weights are Ultralytics **AGPL-3.0**. For closed-source redistribution, use a differently licensed model via `/data/models`.
