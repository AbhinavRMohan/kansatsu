# FILE: src/kansatsu/__init__.py

__version__ = "0.1.5"

from .agent import Kansatsu

# This allows users to do `from kansatsu import Kansatsu`
# instead of `from kansatsu.agent import Kansatsu`
__all__ = ["Kansatsu"]
