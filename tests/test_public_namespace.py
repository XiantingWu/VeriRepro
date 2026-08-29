from __future__ import annotations

import reproagent
import verirepro
from reproagent.cli import main as legacy_cli_main
from verirepro import reprobench
from verirepro.cli import main as public_cli_main


def test_public_namespace_matches_legacy_api() -> None:
    assert verirepro.__version__ == reproagent.__version__
    assert tuple(verirepro.__all__) == tuple(reproagent.__all__)
    for name in verirepro.__all__:
        assert getattr(verirepro, name) is getattr(reproagent, name)


def test_public_namespace_has_explicit_exports() -> None:
    assert set(verirepro.__all__) == {
        "ReproductionPlan",
        "build_reproduction_plan",
        "reproduce",
    }


def test_public_cli_is_the_same_implementation_as_compatibility_cli() -> None:
    assert public_cli_main is legacy_cli_main


def test_public_reprobench_surface_is_explicit_and_resolvable() -> None:
    assert reprobench.__all__
    assert len(reprobench.__all__) == len(set(reprobench.__all__))
    for name in reprobench.__all__:
        assert getattr(reprobench, name) is not None
