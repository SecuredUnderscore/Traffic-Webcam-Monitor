# TrafficWatch: CPU image (default). See Dockerfile.gpu for NVIDIA GPU support.

# 1. Export the YOLO detectors to ONNX so the runtime image needs no PyTorch.
FROM python:3.12-slim AS models
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.14.1 torchvision --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir ultralytics==8.4.178 onnx onnxslim
WORKDIR /export
COPY scripts/export_models.py .
ARG MODELS=yolo11n,yolo11s,yolo11m,yolo26n,yolo26s,yolo26m
RUN python export_models.py /models "$MODELS"

# 2. Build the web UI.
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 3. Runtime.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TW_DATA_DIR=/data TW_MODELS_DIR=/app/models TW_STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=models /models ./models
COPY --from=ui /ui/dist ./static
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
