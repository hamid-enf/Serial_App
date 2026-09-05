# Promo renderer

Renders the launch clip for the application. Nothing here is a mock-up: the
real `MainWindow` is created offscreen and driven frame by frame (no timers, no
threads, no wall-clock sleeps), grabbed, and composited onto a branded
background with Persian titles. Because the footage comes from the shipping
code, it cannot drift out of date the way a hand-edited screen recording does.

## Requirements

- The project's own runtime dependencies (`pip install -r requirements.txt`)
- `ffmpeg` on `PATH`, or `FFMPEG=/path/to/ffmpeg`
- [Vazirmatn](https://github.com/rastikerdar/vazirmatn/releases) TTFs for the
  Persian titles: unpack them and set `PROMO_FONT_DIR=<…>/fonts/ttf`
- Voice-over takes as `NN.wav` in one directory (`--vo`, default `/tmp/vo`)

## Usage

```bash
# 1. Lay the narration out: tempo, gaps, loudness normalisation
python scripts/promo/build_narration.py --vo /tmp/vo --out /tmp/vo/mix.wav

# 2. Render. Both cuts share one timeline, derived from the same audio.
python scripts/promo/render_promo.py --aspect 16x9 --out promo/clip-16x9.mp4
python scripts/promo/render_promo.py --aspect 9x16 --out promo/clip-9x16.mp4

# Inspect a single moment without rendering a whole video:
python scripts/promo/render_promo.py --preview 18.0 --out /tmp/frame.png
```

On a headless machine, prefix with `QT_QPA_PLATFORM=offscreen`.

## Structure

| Piece | Role |
| --- | --- |
| `build_narration.py` | Concatenates the voice-over takes with gaps and writes the mix |
| `vo_layout()` | The single source of truth for *when* each line is spoken |
| `Driver` | Owns the real `MainWindow` and exposes scene-level state changes |
| `Compositor` | Background, rounded window with shadow, Persian typography |
| `Renderer.scene_*` | One method per beat of the timeline |

To change the script, edit `build_timeline()` and the `scene_*` methods — the
picture follows the narration timings automatically.
