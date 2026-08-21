"""
Pytest configuration for masova-support tests.
"""
import sys
from pathlib import Path

_src = str(Path(__file__).parent.parent / "src")
# Insert at position 0 AND remove any path entry pointing at the legacy
# top-level masova_agent/ package so src/masova_agent/ always wins.
_root = str(Path(__file__).parent.parent)
if _root in sys.path:
    sys.path.remove(_root)
if _src not in sys.path:
    sys.path.insert(0, _src)

collect_ignore = ["test_scenarios.py"]
