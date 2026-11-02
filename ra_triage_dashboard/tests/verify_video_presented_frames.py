"""Check recorded compositor pixels; used by the manual browser regression."""
import json
from pathlib import Path
import statistics
import sys

from PIL import Image


def main():
    root = Path(sys.argv[1])
    data = json.loads((root / "results.json").read_text())
    palette = {"bev": (34, 73, 199), "t0": (239, 18, 239),
               "target23": (60, 161, 240), "frame0": (20, 239, 39), "neutral": (5, 7, 10)}
    checked = []
    for row in data["results"]:
        samples = []
        for name in row["frames"]:
            with Image.open(root / name) as image:
                image = image.convert("RGB")
                x = round(row["point"]["x"] * image.width / row["width"])
                y = round(row["point"]["y"] * image.width / row["width"])
                rgb = tuple(round(statistics.median(image.getpixel((x + dx, y + dy))[channel]
                    for dx in [-1, 0, 1] for dy in [-1, 0, 1])) for channel in range(3))
            color, distance = min(((key, sum((a - b) ** 2 for a, b in zip(rgb, value)))
                                   for key, value in palette.items()), key=lambda item: item[1])
            assert distance < 1200 and color in row["expected"], f"wrong presented frame: {name}: {rgb} ({color})"
            samples.append({"file": name, "rgb": rgb, "color": color})
        assert row["paused"], f"unexpected autoplay: {row['phase']}"
        checked.append({key: row[key] for key in ["view", "width", "phase", "time", "initialRequests"]} | {"samples": samples})
    result = {"scenarios": len(checked), "frames": sum(len(row["samples"]) for row in checked), "checks": checked}
    (root / "pixel-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"pixel_scenarios": result["scenarios"], "pixel_frames": result["frames"], "wrong_frames": 0}))


if __name__ == "__main__":
    main()
