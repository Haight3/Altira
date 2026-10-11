"""Select an explicitly requested online DEM provider.

Copyright (C) 2026
"""

from typing import Literal

from .copernicus import Copernicus
from .opentopography import OpenTopography, OpenTopographySource

Source = Literal["copernicus", OpenTopographySource]


def create_provider(*, cache_dir: str, source: Source = "copernicus", resolution: Literal[30, 90] = 30) -> Copernicus | OpenTopography:
    """Select a provider that enforces its own supported native resolutions.

    Parameters
    ----------
    cache_dir : str
        Persistent cache root.
    source : Source, default="copernicus"
        Explicit source, with no automatic fallback to other datasets.
    resolution : {30, 90}, default=30
        Requested native resolution in meters.

    Returns
    -------
    Copernicus or OpenTopography
        Lazy provider with tile discovery and download operations.
    """
    if source == "copernicus":
        return Copernicus(cache_dir=cache_dir, resolution=resolution)
    return OpenTopography(cache_dir=cache_dir, source=source, resolution=resolution)
