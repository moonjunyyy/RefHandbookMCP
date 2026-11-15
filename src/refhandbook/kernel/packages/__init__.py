"""Packages: vocabularies and rules installed into a kernel graph (sealed; the user's to change).

research carries rules and has its own upgrade (runtime.upgrade_packages); the VOCABULARIES only define types,
and each is installed when its own digest changes, independently of the research package."""

from . import entry, handbook, research

VOCABULARIES = (handbook, entry)

__all__ = ["VOCABULARIES", "entry", "handbook", "research"]
