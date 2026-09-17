"""Register the complete SQLAlchemy model graph on package import.

Several services import an individual model module directly.  Importing the
central registry here keeps string-based relationships resolvable in those
standalone processes as well as in the full API application.
"""

from app.models import base as base

__all__ = ["base"]
