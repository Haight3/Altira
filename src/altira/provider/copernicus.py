"""Access the public Copernicus DEM catalog and cache validated local COG tiles.

Copyright (C) 2026
"""

import logging
import os
import re
from typing import Literal

from altira.datasets import TileInfo, identify_tile
from altira.downloads import download_file
from altira.raster import validate_raster

logger = logging.getLogger(__name__)


class Copernicus:
    """A lazily loaded public tile catalog and persistent raster cache.

    The provider is selected explicitly at construction. Missing catalog cells
    are returned as None; HTTP and invalid raster failures propagate.
    """

    def __init__(self, *, cache_dir: str, resolution: Literal[30, 90] = 30) -> None:
        """Select GLO-30 or GLO-90 and its independent cache directory.

        Parameters
        ----------
        cache_dir : str
            Persistent cache root.
        resolution : {30, 90}, default=30
            Copernicus product resolution in meters.

        Raises
        ------
        ValueError
            If resolution is neither 30 nor 90 meters.
        """
        if resolution not in {30, 90}:
            raise ValueError("Copernicus resolution must be 30 or 90 meters.")
        self.resolution = resolution
        self.label = f"Copernicus GLO-{resolution}"
        self.cache_dir = os.path.join(cache_dir, f"copernicus-{resolution}m")
        self.base_url = f"https://copernicus-dem-{resolution}m.s3.amazonaws.com"
        self.tiles: dict[tuple[int, int], TileInfo] | None = None

    def load_catalog(self) -> dict[tuple[int, int], TileInfo]:
        """Read the cached public tile list, downloading and validating it if absent.

        Returns
        -------
        dict of tuple[int, int] to TileInfo
            Available tile metadata indexed by southwest cell coordinates.
        """
        if self.tiles is not None:
            return self.tiles
        catalog_path = os.path.join(self.cache_dir, "tileList.txt")
        if not os.path.isfile(catalog_path):
            download_file(f"{self.base_url}/tileList.txt", catalog_path, validate=self.validate_catalog)
        self.validate_catalog(catalog_path)
        tiles = {}
        with open(catalog_path, encoding="utf-8") as stream:
            for line in stream:
                name = line.strip().rstrip("/")
                if not name:
                    continue
                path = os.path.join(self.cache_dir, name.split("_")[6], name + ".tif")
                legacy_path = os.path.join(self.cache_dir, name + ".tif")
                if not os.path.isfile(path) and os.path.isfile(legacy_path):
                    path = legacy_path
                info = identify_tile(path)
                if info is not None:
                    tiles[int(info.west), int(info.south)] = info
        self.tiles = tiles
        return tiles

    def validate_catalog(self, path: str) -> None:
        """Require conventional tile names for this catalog's advertised resolution.

        Parameters
        ----------
        path : str
            Catalog text file to validate.

        Raises
        ------
        ValueError
            If the catalog is empty or contains invalid tile names.
        """
        spacing = 10 if self.resolution == 30 else 30
        pattern = rf"Copernicus_DSM_COG_{spacing:02d}_[NS]\d{{2}}_00_[EW]\d{{3}}_00_DEM"
        count = 0
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                name = line.strip().rstrip("/")
                if not name:
                    continue
                if not re.fullmatch(pattern, name):
                    raise ValueError(f"Invalid GLO-{self.resolution} tile catalog entry: {name!r}")
                identify_tile(name + ".tif")
                count += 1
        if not count:
            raise ValueError(f"Empty Copernicus tile catalog: {path}")

    def find_tile(self, lon: int, lat: int) -> TileInfo | None:
        """Find a catalog cell without downloading its raster.

        Parameters
        ----------
        lon, lat : int
            Southwest longitude and latitude of the degree cell.

        Returns
        -------
        TileInfo or None
            Available tile metadata, or None for unpublished/ocean cells.
        """
        return self.load_catalog().get((lon, lat))

    def download_tile(self, info: TileInfo) -> str:
        """Download and validate a catalog tile, or reuse its valid local raster.

        Parameters
        ----------
        info : TileInfo
            Catalog metadata identifying the tile and destination path.

        Returns
        -------
        str
            Path of the validated local source raster.
        """
        if os.path.isfile(info.path):
            validate_raster(info.path)
            return info.path
        name = os.path.splitext(os.path.basename(info.path))[0]
        logger.info("Downloading Copernicus GLO-%s tile %s", self.resolution, name)
        download_file(f"{self.base_url}/{name}/{name}.tif", info.path, validate=validate_raster)
        return info.path
