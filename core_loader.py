"""Load the project core without colliding with a host's generic `app` module."""
import hashlib
import importlib.util
import sys
import threading
from pathlib import Path


_lock = threading.RLock()


def load_core(path: Path):
    path = path.resolve()
    source = path.read_bytes()
    digest = hashlib.sha256(str(path).encode() + source).hexdigest()
    name = f"_portfolio_monitor_core_{digest}"
    with _lock:
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            # Compile the exact hashed source, bypassing timestamp-based .pyc caches.
            exec(compile(source, str(path), "exec"), module.__dict__)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module
