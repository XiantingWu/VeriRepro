import tomllib
from pathlib import Path

import reproagent


def test_package_version_matches_pyproject() -> None:
    project = Path(__file__).parents[1]
    data = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    assert reproagent.__version__ == data["project"]["version"]
