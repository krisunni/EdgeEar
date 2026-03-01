# Phase 7 — Frequency Presets

## Objective
Define all frequency presets for the Redmond/Seattle area with both SDR frequencies and web stream URLs.

## Scope
- Preset schema with stream_url support
- Weather, Aviation, Marine, Public Safety, Broadcast categories
- Web stream URLs for NOAA and LiveATC
- SDR-only presets marked for UI greying

---

## Sub-Phase 7.1 — Preset Definitions

### Tasks

| ID | Task | Status |
|---|---|---|
| T019 | Define frequency presets (presets.py) | planned |
| T020 | Add stream_url to preset schema | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/ravensdr/presets.py` | Frequency preset definitions |

### Verification
- 14 presets defined across 5 categories
- Web stream presets have valid URLs
- SDR-only presets have no stream_url
- `GET /api/presets` returns full list

---

## Exit Criteria
- [ ] All presets defined with correct frequencies
- [ ] Web stream URLs validated (NOAA Monterey confirmed live)
- [ ] Category grouping correct
- [ ] Preset schema includes all required fields

## Risks

| Risk | Mitigation |
|---|---|
| Stream URLs change | Document URL format, check wxradio.org/status.xsl |
| LiveATC terms of service | Personal/local use only, document in notes |
