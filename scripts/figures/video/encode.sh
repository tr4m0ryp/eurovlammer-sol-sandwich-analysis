#!/bin/bash
# Encode a recorded walkthrough for the README: H.264 MP4 (the full clip) plus a compact animated
# WebP preview, because GitHub READMEs do not play repo-hosted MP4 inline.
#   scripts/figures/video/encode.sh <raw.webm> <out_dir>
set -euo pipefail
raw=$1 out=$2
mkdir -p "$out"
ffmpeg -y -loglevel error -i "$raw" -c:v libx264 -preset slow -crf 28 -pix_fmt yuv420p \
  -movflags +faststart -an "$out/platform.mp4"
ffmpeg -y -loglevel error -i "$raw" -vf "fps=10,scale=960:-2:flags=lanczos" -c:v libwebp \
  -quality 60 -compression_level 6 -loop 0 -an "$out/platform-preview.webp"
ls -lh "$out/platform.mp4" "$out/platform-preview.webp"
