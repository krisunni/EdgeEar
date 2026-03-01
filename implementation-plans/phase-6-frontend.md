# Phase 6 — Frontend (Console UI)

## Objective
Build the single-page ravenSDR Console web interface with preset selection, signal meter, audio player, and transcript feed.

## Scope
- HTML template (index.html)
- JavaScript logic (ravensdr.js) — Socket.IO client, Web Audio API, UI state
- CSS stylesheet (ravensdr.css) — console-style dark theme

---

## Sub-Phase 6.1 — HTML Structure

### Tasks

| ID | Task | Status |
|---|---|---|
| T016 | Build index.html single-page app | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/templates/index.html` | ravenSDR Console SPA |

### Verification
- Page loads at http://localhost:5000
- All UI sections visible: presets, signal meter, audio, transcript

---

## Sub-Phase 6.2 — JavaScript Logic

### Tasks

| ID | Task | Status |
|---|---|---|
| T017 | Implement ravensdr.js frontend logic | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/static/ravensdr.js` | Frontend logic |

### Verification
- Socket.IO connection established
- Preset clicks trigger tune API call
- Transcript feed updates in real-time
- Signal meter animates
- Audio plays/pauses correctly

---

## Sub-Phase 6.3 — CSS Stylesheet

### Tasks

| ID | Task | Status |
|---|---|---|
| T018 | Create ravensdr.css stylesheet | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/static/ravensdr.css` | UI stylesheet |

### Verification
- Console-style dark theme renders correctly
- Responsive layout
- Signal meter colors (green/yellow/red)
- Transcript entry slide-in animation

---

## Exit Criteria
- [ ] Full UI renders and is functional
- [ ] Preset selection tunes radio
- [ ] Signal meter updates live
- [ ] Audio streams to browser
- [ ] Transcript feed shows live text with auto-scroll
- [ ] Squelch/gain controls work
- [ ] Mode badge shows SDR or WEB STREAM

## Risks

| Risk | Mitigation |
|---|---|
| Cross-browser audio compatibility | Test Chrome + Firefox, use Web Audio API fallback |
| Socket.IO reconnection | Auto-reconnect with connection banner |
