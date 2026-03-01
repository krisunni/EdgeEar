# Phase 5 — Backend API (Flask App)

## Objective
Implement the Flask application with REST routes, Socket.IO events, and thread orchestration.

## Scope
- Flask routes: `/`, `/api/presets`, `/api/tune`, `/api/stop`, `/api/squelch`, `/api/gain`, `/api/status`
- Socket.IO events: transcript, status, signal_level, mode, error
- Thread management: 4 concurrent threads
- Audio stream route integration

---

## Sub-Phase 5.1 — REST Routes

### Tasks

| ID | Task | Status |
|---|---|---|
| T013 | Implement Flask app with REST routes | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/ravensdr/app.py` | Flask app, routes, Socket.IO events |

### Verification
- `GET /api/presets` returns JSON preset list
- `POST /api/tune` switches frequency
- `GET /api/status` returns current state
- `POST /api/stop` stops audio source

---

## Sub-Phase 5.2 — Socket.IO Events

### Tasks

| ID | Task | Status |
|---|---|---|
| T014 | Implement Socket.IO event emitters | planned |

### Verification
- `transcript` events arrive in browser with correct payload
- `signal_level` events fire every 500ms
- `mode` event sent on client connect
- `error` events show in browser

---

## Sub-Phase 5.3 — Thread Orchestration

### Tasks

| ID | Task | Status |
|---|---|---|
| T015 | Implement thread orchestration | planned |

### Verification
- All 4 threads start on app launch
- Clean shutdown on SIGTERM
- No thread deadlocks

---

## Exit Criteria
- [ ] All REST routes functional
- [ ] Socket.IO events delivered to browser
- [ ] 4 threads running concurrently
- [ ] App starts and serves UI at http://localhost:5000

## Risks

| Risk | Mitigation |
|---|---|
| eventlet monkey-patching conflicts | Import eventlet before all other imports |
| Thread safety on shared queues | Use thread-safe queue.Queue |
