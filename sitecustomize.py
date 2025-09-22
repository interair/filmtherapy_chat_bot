import sys
import os
import time
import builtins
import atexit
import threading

# Timestamp at interpreter start (used by src.profiling.since_interpreter_start)
t0 = time.monotonic()
sys.stderr.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [sitecustomize] Python interpreter started\n")
sys.stderr.flush()


def _env_truthy(name: str, default: str = "0") -> bool:
    val = os.getenv(name, default)
    return str(val).lower() not in ("", "0", "false", "no", "off", "none")


# Optional: import-time profiling to find slow imports during cold start.
# Enabled when APP_PROFILE_STARTUP=1. Threshold configurable via APP_PROFILE_IMPORT_THRESHOLD_MS.
if _env_truthy("APP_PROFILE_STARTUP"):
    try:
        _threshold_ms = float(os.getenv("APP_PROFILE_IMPORT_THRESHOLD_MS", "10") or "10")
    except Exception:
        _threshold_ms = 10.0

    _events: list[tuple[float, str]] = []
    _orig_import = builtins.__import__
    _tls = threading.local()

    def _prof_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[override]
        # Prevent recursion if imports happen inside our wrapper
        if getattr(_tls, "busy", False):
            return _orig_import(name, globals, locals, fromlist, level)
        _tls.busy = True
        t_start = time.perf_counter()
        try:
            return _orig_import(name, globals, locals, fromlist, level)
        finally:
            dt_ms = (time.perf_counter() - t_start) * 1000.0
            _tls.busy = False
            if dt_ms >= _threshold_ms:
                try:
                    sys.stderr.write(
                        f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [import] {name} {dt_ms:.1f} ms\n"
                    )
                    sys.stderr.flush()
                except Exception:
                    pass
                try:
                    _events.append((dt_ms, name))
                except Exception:
                    pass

    builtins.__import__ = _prof_import  # type: ignore[assignment]

    def _summary() -> None:
        if not _events:
            return
        try:
            sys.stderr.write(
                f"{time.strftime('%Y-%m-%dT%H:%M:%S')} [import] slow imports summary (>{_threshold_ms:.1f} ms):\n"
            )
            for dt, mod in sorted(_events, key=lambda x: x[0], reverse=True)[:50]:
                sys.stderr.write(f"  {dt:.1f} ms  {mod}\n")
            sys.stderr.flush()
        except Exception:
            # Best-effort only
            pass

    atexit.register(_summary)
