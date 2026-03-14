#!/usr/bin/env bash
# Convert Motion Canvas rendered output to an optimized GIF.
#
# Usage:
#   1. Start the editor: npm run serve
#   2. In the Motion Canvas editor, set: 1920x1080, 30fps, FFmpeg exporter
#   3. Click RENDER — output goes to ./output/
#   4. Run this script: ./render-gif.sh
#
# Requires: ffmpeg

set -euo pipefail

INPUT_DIR="./output"
OUTPUT_GIF="./output/pipeline_overview.gif"
FINAL_DEST="../../pipeline_overview/pipeline_overview.gif"

# Find the rendered video
VIDEO=$(find "$INPUT_DIR" -maxdepth 2 -name "*.mp4" -o -name "*.webm" | head -1)

if [ -z "$VIDEO" ]; then
  echo "No video file found in $INPUT_DIR. Render from the editor first."
  echo "Falling back to image sequence..."

  FRAMES_DIR=$(find "$INPUT_DIR" -maxdepth 2 -type d -name "project" | head -1)
  if [ -z "$FRAMES_DIR" ]; then
    FRAMES_DIR="$INPUT_DIR"
  fi

  FIRST_FRAME=$(find "$FRAMES_DIR" -name "*.png" | head -1)
  if [ -z "$FIRST_FRAME" ]; then
    echo "Error: No frames or video found in $INPUT_DIR"
    exit 1
  fi

  echo "Using image sequence from $FRAMES_DIR"
  # Two-pass palette optimization for image sequence
  ffmpeg -y -framerate 30 -pattern_type glob -i "${FRAMES_DIR}/*.png" \
    -vf "fps=15,scale=1200:-1:flags=lanczos,palettegen=stats_mode=diff" \
    /tmp/palette_langrag.png

  ffmpeg -y -framerate 30 -pattern_type glob -i "${FRAMES_DIR}/*.png" \
    -i /tmp/palette_langrag.png \
    -filter_complex "fps=15,scale=1200:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5" \
    "$OUTPUT_GIF"
else
  echo "Converting $VIDEO to GIF..."
  # Two-pass palette optimization
  ffmpeg -y -i "$VIDEO" \
    -vf "fps=15,scale=1200:-1:flags=lanczos,palettegen=stats_mode=diff" \
    /tmp/palette_langrag.png

  ffmpeg -y -i "$VIDEO" \
    -i /tmp/palette_langrag.png \
    -filter_complex "fps=15,scale=1200:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5" \
    "$OUTPUT_GIF"
fi

SIZE=$(du -h "$OUTPUT_GIF" | cut -f1)
echo ""
echo "GIF created: $OUTPUT_GIF ($SIZE)"

# Copy to final destination
if [ -d "$(dirname "$FINAL_DEST")" ]; then
  cp "$OUTPUT_GIF" "$FINAL_DEST"
  echo "Copied to: $FINAL_DEST"
fi
