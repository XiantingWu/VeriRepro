from __future__ import annotations

import reproagent
import verirepro


def test_public_namespace_matches_legacy_api() -> None:
    assert verirepro.__version__ == reproagent.__version__
    assert verirepro.reproduce is reproagent.reproduce
    assert verirepro.ReproductionPlan is reproagent.ReproductionPlan
    assert verirepro.build_reproduction_plan is reproagent.build_reproduction_plan


def test_public_namespace_has_explicit_exports() -> None:
    assert set(verirepro.__all__) == {
        "ReproductionPlan",
        "build_reproduction_plan",
        "reproduce",
    }
