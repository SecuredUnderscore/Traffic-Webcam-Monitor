"""Export the bundled YOLO detectors to ONNX.

Runs only in the Docker "models" build stage, so the runtime image needs
onnxruntime instead of PyTorch + Ultralytics (~1.5 GB smaller).
"""

import json
import shutil
import sys
from pathlib import Path

from ultralytics import YOLO

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/models")
MODELS = sys.argv[2].split(",") if len(sys.argv) > 2 else ["yolo11n", "yolo11s", "yolo11m"]

OUT.mkdir(parents=True, exist_ok=True)
manifest = []
for name in MODELS:
    model = YOLO(f"{name}.pt")
    onnx_path = Path(model.export(format="onnx", imgsz=640, opset=17, simplify=True, dynamic=False))
    dest = OUT / f"{name}.onnx"
    shutil.move(str(onnx_path), dest)
    manifest.append({
        "id": name,
        "file": dest.name,
        "input_size": 640,
        "classes": model.names,
        "source": "ultralytics",
        "license": "AGPL-3.0",
    })
    print(f"exported {name} -> {dest} ({dest.stat().st_size / 1e6:.1f} MB)")

(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
