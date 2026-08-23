from __future__ import annotations

from pathlib import Path

import pytest

from reproagent import config


def _manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "verirepro.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_manifest_rejects_yaml_aliases(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        """version: 1
experiment: &experiment
  command: python reproduce.py
copy: *experiment
""",
    )
    with pytest.raises(ValueError, match="aliases are not allowed"):
        config.load_manifest(path)


def test_manifest_rejects_duplicate_mapping_keys(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        """version: 1
experiment:
  command: python first.py
  command: python second.py
""",
    )
    with pytest.raises(ValueError, match="duplicate mapping key"):
        config.load_manifest(path)


def test_manifest_rejects_non_boolean_network_request(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        'version: 1\nexperiment:\n  network: "false"\n',
    )
    with pytest.raises(ValueError, match="experiment.network must be a boolean"):
        config.load_manifest(path)


def test_manifest_bounds_dataset_spec_count(tmp_path: Path) -> None:
    datasets = "\n".join(
        f"  - name: dataset-{index}\n    url: https://example.org/{index}.bin"
        for index in range(config._MAX_DATASET_SPECS + 1)
    )
    path = _manifest(tmp_path, f"version: 1\ndatasets:\n{datasets}\n")
    with pytest.raises(ValueError, match="datasets exceeds host safety limit"):
        config.load_manifest(path)


def test_manifest_rejects_non_finite_scientific_values(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        """version: 1
metrics:
  - name: accuracy
    paper: .nan
    tolerance: 0.01
""",
    )
    with pytest.raises(ValueError, match="metric paper value must be a finite number"):
        config.load_manifest(path, trust_scientific_contract=True)
