"""Aircraft-specific DCS-BIOS normalization adapters."""

from .base import AircraftAdapter
from .fa18c import FA18CAdapter
from .generic import GenericAircraftAdapter

__all__ = ["AircraftAdapter", "FA18CAdapter", "GenericAircraftAdapter"]
