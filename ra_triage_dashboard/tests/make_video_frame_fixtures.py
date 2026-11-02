"""Generate small, distinct-color media for the manual compositor regression."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sources = {
        "bev": "color=c=0x234ac8:s=320x180:r=10:d=40",
        "closeup": "color=c=black:s=320x180:r=10:d=40,"
            "geq=r='if(lt(T,19.95),20,if(lt(T,22.95),240,60))':"
            "g='if(lt(T,19.95),240,if(lt(T,22.95),20,160))':"
            "b='if(lt(T,19.95),40,if(lt(T,22.95),240,240))'",
    }
    for name, source in sources.items():
        clip, poster = args.output / (name + ".mp4"), args.output / (name + ".png")
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", source,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "20", "-sc_threshold", "0",
            "-threads", "2", "-movflags", "+faststart", str(clip)], check=True, timeout=60)
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", "20", "-i", str(clip),
            "-frames:v", "1", str(poster)], check=True, timeout=20)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
