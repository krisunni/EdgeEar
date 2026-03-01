# Graceful Shutdown Plan — No Orphaned Processes

## Context
The app can leave orphaned processes (rtl_fm, ffmpeg, Hailo NPU) when exiting because:
- `sys.exit(0)` in the signal handler is aggressive and may bypass cleanup
- No `atexit` safety net for unexpected exits (crashes, unhandled exceptions)
- Unread stderr pipes can block subprocesses from exiting
- Reader threads aren't joined, so stop() can return before threads finish

## Changes (4 files)

### 1. `code/ravensdr/app.py` — Cooperative shutdown + atexit safety net
- Replace `sys.exit(0)` with cooperative shutdown (let eventlet exit naturally)
- Add `atexit.register()` as safety net for unexpected exits
- Make `shutdown()` idempotent with a `_shutdown_called` guard (safe to call multiple times)
- For SIGTERM, explicitly call `socketio.stop()`
- Restore `SIG_DFL` for SIGINT after first cleanup so double Ctrl+C force-kills

### 2. `code/ravensdr/transcriber.py` — Release model refs in stop()
- After thread join, set `_whisper_model = None` to let GC free resources
- Log warning if thread doesn't exit within 5s timeout

### 3. `code/ravensdr/tuner.py` — Close pipes, join thread, harden read loop
- Close stdout/stderr pipes before `terminate()` to prevent blocked I/O
- Increase wait timeout from 1s to 2s
- Join reader thread before returning from `stop()`
- Catch `ValueError`/`OSError` in `_read_loop` when pipes are closed during shutdown

### 4. `code/ravensdr/stream_source.py` — Same pattern as tuner.py
- Close stdout/stderr pipes before `terminate()`
- Join reader thread before returning from `stop()`
- Catch `ValueError`/`OSError` in `_read_loop`

## Shutdown Sequence (after changes)
1. Signal → `shutdown()` → sets stop event, calls `input_source.stop()` + `transcriber.stop()`
2. Subprocesses: pipes closed → terminate → wait(2s) → kill if needed → thread joined
3. Transcriber: stop event → inference loop exits → Hailo context managers unwind → model refs cleared
4. SIGINT: KeyboardInterrupt exits eventlet naturally. SIGTERM: `socketio.stop()` explicit
5. `atexit` fires but is no-op (idempotent guard)
6. Double Ctrl+C = force-kill escape hatch

## Verification
- Run the app, tune to a station, then Ctrl+C — confirm clean exit log and no orphaned processes (`ps aux | grep -E 'rtl_fm|ffmpeg'`)
- Run the app, tune, then `kill <pid>` (SIGTERM) — same check
- Kill with unhandled exception (e.g., inject `raise RuntimeError` in a route) — confirm atexit cleans up
