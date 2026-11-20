import shutil
import subprocess
import sys
from pathlib import Path

from pdx import research_catalog


def test_research_imports_from_package_only(tmp_path: Path) -> None:
    source = Path(research_catalog.__file__).parent
    shutil.copytree(source, tmp_path / "pdx", ignore=shutil.ignore_patterns("__pycache__"))
    script = """
import sys
sys.path.insert(0, sys.argv[1])
from pdx.research_catalog import write
assert callable(write)
assert "pdx.situated" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-IB", "-c", script, str(tmp_path)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
