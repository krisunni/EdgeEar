# HTTP audio streaming — WAV header + chunked response

import struct
import logging

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
BITS_PER_SAMPLE = 16


def make_wav_header():
    """Create a WAV header for streaming (size set to 0xFFFFFFFF)."""
    byte_rate = SAMPLE_RATE * CHANNELS * BITS_PER_SAMPLE // 8
    block_align = CHANNELS * BITS_PER_SAMPLE // 8
    max_size = 0xFFFFFFFF

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        max_size,           # file size (streaming — max)
        b"WAVE",
        b"fmt ",
        16,                 # chunk size
        1,                  # PCM format
        CHANNELS,
        SAMPLE_RATE,
        byte_rate,
        block_align,
        BITS_PER_SAMPLE,
        b"data",
        max_size,           # data size (streaming — max)
    )
    return header


def audio_stream_generator(audio_queue):
    """Generator that yields WAV header then PCM chunks from the queue."""
    yield make_wav_header()
    while True:
        try:
            chunk = audio_queue.get(timeout=5)
            yield chunk
        except Exception:
            # Timeout — yield silence to keep connection alive
            yield b"\x00" * 4096
