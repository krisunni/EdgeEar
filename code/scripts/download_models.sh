#!/usr/bin/env bash
# Download Hailo-8L Whisper model files for ravenSDR
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODELS_DIR="$SCRIPT_DIR/../ravensdr/models"

S3_BASE="https://hailo-csdata.s3.eu-west-2.amazonaws.com/resources"

GREEN='\033[0;32m'
NC='\033[0m'
pass() { echo -e "${GREEN}[OK]${NC} $1"; }

echo "ravenSDR — Downloading Hailo-8L Whisper models"
echo ""

# --- HEF files (encoder + decoder) ---
HEF_DIR="$MODELS_DIR/h8l"
mkdir -p "$HEF_DIR"

if [ -f "$HEF_DIR/tiny-whisper-encoder-10s_15dB_h8l.hef" ] && \
   [ -f "$HEF_DIR/tiny-whisper-decoder-fixed-sequence-matmul-split_h8l.hef" ]; then
    pass "HEF files already present"
else
    echo "Downloading encoder HEF..."
    wget -q --show-progress -P "$HEF_DIR" \
        "$S3_BASE/hefs/h8l_rpi/tiny-whisper-encoder-10s_15dB_h8l.hef"

    echo "Downloading decoder HEF..."
    wget -q --show-progress -P "$HEF_DIR" \
        "$S3_BASE/hefs/h8l_rpi/tiny-whisper-decoder-fixed-sequence-matmul-split_h8l.hef"

    pass "HEF files downloaded"
fi

# --- Decoder assets (token embedding + positional bias) ---
ASSETS_DIR="$MODELS_DIR/decoder_assets"
mkdir -p "$ASSETS_DIR"

if [ -f "$ASSETS_DIR/token_embedding_weight_tiny.npy" ] && \
   [ -f "$ASSETS_DIR/onnx_add_input_tiny.npy" ]; then
    pass "Decoder assets already present"
else
    echo "Downloading token embedding weights..."
    wget -q --show-progress -O "$ASSETS_DIR/token_embedding_weight_tiny.npy" \
        "$S3_BASE/npy%20files/whisper/decoder_assets/tiny/decoder_tokenization/token_embedding_weight_tiny.npy"

    echo "Downloading positional bias..."
    wget -q --show-progress -O "$ASSETS_DIR/onnx_add_input_tiny.npy" \
        "$S3_BASE/npy%20files/whisper/decoder_assets/tiny/decoder_tokenization/onnx_add_input_tiny.npy"

    pass "Decoder assets downloaded"
fi

# --- mel_filters.npz (should already be in-tree, but verify) ---
if [ ! -f "$MODELS_DIR/mel_filters.npz" ]; then
    echo "WARNING: mel_filters.npz not found at $MODELS_DIR/mel_filters.npz"
    echo "This file should be checked into the repository."
else
    pass "mel_filters.npz present"
fi

echo ""
echo "All model files ready in $MODELS_DIR"
