"""Public Altira elevation-query API and package version.

The package exports the DEM query classes and the installed package version.
"""

from .dem import Dem, DemTile
from .version import __version__
