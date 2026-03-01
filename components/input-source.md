# Input Source Abstraction

## Overview
Unified interface wrapping Tuner (SDR) and StreamSource (web stream) behind a common PCM queue — downstream components are source-agnostic.

## Status
`planned` — See [.state/components.json](../.state/components.json)

## Technology
Python, queue

## Interfaces
- **Input:** Mode detection via `rtl_test`, preset parameters
- **Output:** `pcm_queue` (Queue, maxsize=200) with 4096-byte PCM chunks

## Dependencies
- `tuner` component (SDR mode)
- `stream-source` component (web stream mode)

## Notes
See [architecture/design.md](../architecture/design.md) §3.3 for full specification.
