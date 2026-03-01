# SDR Radio Reception

## Overview
Tune RTL-SDR Blog V4 to preset frequencies, demodulate FM/AM/WBFM/SSB via rtl_fm, output 16kHz mono PCM.

## Status
`planned` — See [.state/features.json](../.state/features.json)

## Components
- [tuner](../components/tuner.md)
- [input-source](../components/input-source.md)

## Requirements
- RTL-SDR Blog V4 connected via USB
- `rtl-sdr` package installed
- DVB kernel module blacklisted

## Implementation Notes
See [implementation-plans/phase-2-input-source.md](../implementation-plans/phase-2-input-source.md)

## Exit Criteria
- [ ] rtl_fm starts and produces PCM output
- [ ] Frequency switching works (kill + restart subprocess)
- [ ] Squelch and gain controls functional
