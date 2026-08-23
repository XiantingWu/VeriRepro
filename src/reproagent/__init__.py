"""VeriRepro public package.

The Python import path remains ``reproagent`` for backward compatibility while
public packaging and the preferred CLI use the VeriRepro name.
"""

from .core import ReproductionPlan, build_reproduction_plan
from .pipeline import reproduce

__all__ = ["ReproductionPlan", "build_reproduction_plan", "reproduce"]
__version__ = "0.8.0"
