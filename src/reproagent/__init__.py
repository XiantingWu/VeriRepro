"""Legacy VeriRepro compatibility and implementation namespace.

New integrations should import :mod:`verirepro`. The ``reproagent`` import and
CLI remain compatibility aliases during the 0.x series; their documented public
symbols are contract-tested against the preferred namespace.
"""

from .core import ReproductionPlan, build_reproduction_plan
from .pipeline import reproduce

__all__ = ["ReproductionPlan", "build_reproduction_plan", "reproduce"]
__version__ = "0.8.1"
