from __future__ import annotations

import argparse
import csv
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


def gpu() -> list[str]:
    command = ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits"]
    try:
        return subprocess.check_output(command, text=True, timeout=5).strip().split(", ")
    except Exception:
        return ["", "", "", "", ""]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, default=Path("validation/results/hardware.csv"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "cpu_percent", "ram_percent", "gpu_percent", "vram_used_mb", "vram_total_mb", "gpu_temp_c", "gpu_power_w"])
        for _ in range(args.seconds):
            writer.writerow([datetime.now(timezone.utc).isoformat(), psutil.cpu_percent(), psutil.virtual_memory().percent, *gpu()])
            handle.flush()
            time.sleep(1)
