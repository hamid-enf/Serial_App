#!/usr/bin/env python3
"""Assemble the narration track for the promo clip.

Takes the individual voice-over takes, speeds them up slightly, lays them out
with breathing room between lines, and writes a single mix whose timings match
``render_promo.vo_layout`` exactly.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import wave
from pathlib import Path

ORDER = ["01", "02", "03", "04", "05", "06", "08"]


def duration(ffprobe: str, path: Path) -> float:
    """Length in seconds. WAV is read directly so no ffprobe is required."""
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    out = subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vo", type=Path, default=Path("/tmp/vo"))
    parser.add_argument("--out", type=Path, default=Path("/tmp/vo/mix.wav"))
    parser.add_argument("--tempo", type=float, default=1.10)
    parser.add_argument("--gap", type=float, default=0.28)
    parser.add_argument("--lead-in", type=float, default=1.15)
    parser.add_argument("--tail", type=float, default=1.7)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    cursor = args.lead_in
    plan: list[tuple[str, float, float]] = []

    for index, name in enumerate(ORDER):
        path = args.vo / f"{name}.wav"
        inputs += ["-i", str(path)]
        length = duration(args.ffprobe, path) / args.tempo
        delay_ms = int(round(cursor * 1000))
        filters.append(
            f"[{index}:a]atempo={args.tempo},"
            f"adelay={delay_ms}|{delay_ms},"
            f"apad=pad_dur=0.05[a{index}]"
        )
        labels.append(f"[a{index}]")
        plan.append((name, cursor, cursor + length))
        cursor += length + args.gap

    total = cursor - args.gap + args.tail
    mix = (
        "".join(labels)
        + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[m];"
        f"[m]loudnorm=I=-15:TP=-1.5:LRA=11,apad,atrim=0:{total:.3f},"
        "asetpts=N/SR/TB[out]"
    )
    graph = ";".join(filters) + ";" + mix

    cmd = [args.ffmpeg, "-y", "-loglevel", "error", *inputs,
           "-filter_complex", graph, "-map", "[out]",
           "-ar", "48000", "-ac", "2", str(args.out)]
    subprocess.run(cmd, check=True)

    for name, start, end in plan:
        print(f"  VO {name}: {start:6.2f} → {end:6.2f}s")
    print(f"total {total:.2f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
