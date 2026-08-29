"""Preferred public Python API for VeriRepro.

The implementation remains shared with :mod:`reproagent` during the 0.x
compatibility window. New integrations should import from :mod:`verirepro`.
"""

from reproagent import ReproductionPlan, build_reproduction_plan, reproduce
from reproagent import __version__ as __version__

__all__ = ["ReproductionPlan", "build_reproduction_plan", "reproduce"]
