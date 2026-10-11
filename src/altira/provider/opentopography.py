"""Discover and download anonymous OpenTopography ALOS and SRTM bulk tiles.

Copyright (C) 2026
"""

import logging
import os
import re
from typing import Literal

from defusedxml import ElementTree

from altira.datasets import Datum, TileInfo
from altira.downloads import download_file
from altira.raster import validate_raster

OpenTopographySource = Literal["alos", "alos-ellipsoidal", "srtm", "srtm-ellipsoidal"]

logger = logging.getLogger(__name__)


class OpenTopography:
    """A public VRT tile index and independent cache of native source rasters.

    The bulk storage endpoints support anonymous HTTPS downloads. VRT files
    are parsed only as catalogs; GDAL never opens their external references.
    """

    def __init__(self, *, cache_dir: str, source: OpenTopographySource = "alos", resolution: Literal[30, 90] = 30) -> None:
        """Select one ALOS/SRTM product and its native vertical datum.

        Parameters
        ----------
        cache_dir : str
            Persistent cache root.
        source : {"alos", "alos-ellipsoidal", "srtm", "srtm-ellipsoidal"}, default="alos"
            Product to download from anonymous OpenTopography bulk storage.
        resolution : {30, 90}, default=30
            SRTM supports 30/90 meters; other sources support only 30 meters.

        Raises
        ------
        ValueError
            If the source or its requested native resolution is unsupported.
        """
        if resolution not in {30, 90}:
            raise ValueError("DEM resolution must be 30 or 90 meters.")
        suffix = "_wgs84" if source.endswith("-ellipsoidal") else ""
        if source in {"alos", "alos-ellipsoidal"}:
            if resolution != 30:
                raise ValueError(f"{source} supports only native 30-meter resolution.")
            self.dataset = "AW3D30_E" if suffix else "AW3D30"
            self.catalog_name = self.dataset + "_global.vrt"
            self.filename_pattern = rf"ALPSMLC30_([NS]\d{{3}})([EW]\d{{3}})_DSM{suffix}\.tif"
        elif source in {"srtm", "srtm-ellipsoidal"}:
            if suffix and resolution != 30:
                raise ValueError("srtm-ellipsoidal supports only native 30-meter resolution.")
            self.dataset = "SRTM_GL1_Ellip" if suffix else f"SRTM_GL{1 if resolution == 30 else 3}"
            self.catalog_name = self.dataset + "_srtm.vrt"
            self.filename_pattern = rf"([NS]\d{{2}})([EW]\d{{3}}){suffix}\.tif"
        else:
            raise ValueError(f"Unknown DEM source {source!r}; expected alos, alos-ellipsoidal, srtm, or srtm-ellipsoidal.")
        self.source_datum: Datum = "wgs84" if suffix else "egm96"
        self.resolution = resolution
        self.label = f"{source} {resolution} m"
        self.cache_dir = os.path.join(cache_dir, "opentopography", self.dataset)
        self.base_url = "https://opentopography.s3.sdsc.edu/raster"
        self.tiles: dict[tuple[int, int], TileInfo] | None = None

    def read_catalog(self, path: str) -> dict[tuple[int, int], TileInfo]:
        """Parse and validate relative tile references in this product's VRT.

        Parameters
        ----------
        path : str
            Catalog filename.

        Returns
        -------
        dict of tuple[int, int] to TileInfo
            Native tile metadata indexed by southwest degree coordinates.

        Raises
        ------
        ValueError
            If the catalog is empty, ambiguous, or contains unexpected paths.
        """
        root = ElementTree.parse(path).getroot()
        if root.tag != "VRTDataset":
            raise ValueError(f"Expected an OpenTopography VRT tile catalog: {path}")
        tiles = {}
        for entry in root.iter("SourceFilename"):
            relative = (entry.text or "").strip()
            parts = relative.split("/")
            match = re.fullmatch(self.filename_pattern, parts[-1])
            if (
                entry.get("relativeToVRT") != "1"
                or not relative.startswith(self.catalog_name.removesuffix(".vrt") + "/")
                or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in {".", ".."} for part in parts)
                or match is None
            ):
                raise ValueError(f"Invalid {self.dataset} catalog entry: {relative!r}")
            latitude, longitude = match[1], match[2]
            south = int(latitude[1:]) * (1 if latitude[0] == "N" else -1)
            west = int(longitude[1:]) * (1 if longitude[0] == "E" else -1)
            if not (-180 <= west < 180 and -90 <= south < 90):
                raise ValueError(f"Invalid geographic coordinates in {self.dataset} catalog entry: {relative!r}")
            info = TileInfo(os.path.join(self.cache_dir, *parts), west, west + 1, south, south + 1, self.source_datum, self.resolution)
            cell = (west, south)
            if cell in tiles:
                raise ValueError(f"Duplicate degree cell in {self.dataset} catalog: {cell}")
            tiles[cell] = info
        if not tiles:
            raise ValueError(f"Empty OpenTopography tile catalog: {path}")
        return tiles

    def validate_catalog(self, path: str) -> None:
        """Validate the product catalog before publishing a downloaded file.

        Parameters
        ----------
        path : str
            Catalog filename to validate.
        """
        self.read_catalog(path)

    def load_catalog(self) -> dict[tuple[int, int], TileInfo]:
        """Load the persistent tile index, downloading it if absent.

        Returns
        -------
        dict of tuple[int, int] to TileInfo
            Available native source tiles, without raster downloads.
        """
        if self.tiles is None:
            path = os.path.join(self.cache_dir, self.catalog_name)
            if not os.path.isfile(path):
                download_file(f"{self.base_url}/{self.dataset}/{self.catalog_name}", path, validate=self.validate_catalog)
            self.tiles = self.read_catalog(path)
        return self.tiles

    def find_tile(self, lon: int, lat: int) -> TileInfo | None:
        """Find one published degree cell without downloading its raster.

        Parameters
        ----------
        lon, lat : int
            Southwest longitude and latitude of the degree cell.

        Returns
        -------
        TileInfo or None
            Native tile metadata, or None when the catalog has no coverage.
        """
        return self.load_catalog().get((lon, lat))

    def download_tile(self, info: TileInfo) -> str:
        """Download or validate and reuse the selected native raster.

        Parameters
        ----------
        info : TileInfo
            Catalog metadata identifying the source and destination.

        Returns
        -------
        str
            Validated native source raster path.
        """
        if os.path.isfile(info.path):
            validate_raster(info.path)
            return info.path
        relative = os.path.relpath(info.path, self.cache_dir).replace(os.sep, "/")
        logger.info("Downloading %s tile %s", self.label, os.path.basename(info.path))
        download_file(f"{self.base_url}/{self.dataset}/{relative}", info.path, validate=validate_raster)
        return info.path
