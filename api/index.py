import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUBDIR = ROOT / "spearmint-audit-agent"

for p in (str(ROOT), str(SUBDIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

target_file = SUBDIR / "api" / "index.py"
spec = importlib.util.spec_from_file_location("spearmint_api_index", target_file)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

app = mod.app
handler = mod.handler

__all__ = ["app", "handler"]
