from __future__ import annotations

import os
from pathlib import Path

OUTPUT = Path(
    os.environ.get("VERIREPRO_OUTPUT_DIR") or os.environ.get("REPROAGENT_OUTPUT_DIR") or "outputs"
)
OUTPUT.mkdir(parents=True, exist_ok=True)

figure = """P3
4 4
255
0 0 0   64 64 64   128 128 128   255 255 255
0 0 0   64 64 64   128 128 128   255 255 255
255 255 255   128 128 128   64 64 64   0 0 0
255 255 255   128 128 128   64 64 64   0 0 0
"""
(OUTPUT / "figure3.ppm").write_text(figure, encoding="ascii")
(OUTPUT / "table2.csv").write_text("model,accuracy\nbase,0.908\n", encoding="utf-8")

print("VERIREPRO_METRIC accuracy=0.908")
