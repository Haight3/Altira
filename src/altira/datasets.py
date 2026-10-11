"""Recognize local DEM formats and index their typed tile metadata.

Dataset names supply nominal coverage and vertical datum. Raster samples are
always located using their stored GDAL geotransform.

Copyright (C) 2026
"""

import csv
import math
import os
import re
import tarfile
import zipfile
from dataclasses import dataclass, replace
from typing import Literal

from osgeo import gdal

Datum = Literal["egm96", "egm2008", "wgs84"]


@dataclass(frozen=True)
class TileInfo:
    """Metadata describing one DEM raster.

    Attributes
    ----------
    path : str
        Raster path or GDAL virtual path.
    west, east, south, north : float
        Nominal geographic coverage in degrees.
    source_datum : Datum
        Vertical datum of the source elevations.
    resolution : float
        Nominal horizontal sample spacing in meters.

    """

    path: str
    west: float
    east: float
    south: float
    north: float
    source_datum: Datum
    resolution: float

    def covers(self, lon: int, lat: int) -> bool:
        """Check whether this tile covers the specified integer geographic cell.

        Parameters
        ----------
        lon, lat : int
            Southwest coordinate of the degree cell to test.

        Returns
        -------
        bool
            Whether the cell is inside the nominal tile extent.
        """
        return self.west <= lon < self.east and self.south <= lat < self.north


def identify_tile(path: str) -> TileInfo | None:
    """Recognize local raster formats from their conventional names.

    Parameters
    ----------
    path : str
        Raster filename or path to inspect.

    Returns
    -------
    TileInfo or None
        Recognized tile metadata, or None for unrelated filenames.

    Raises
    ------
    ValueError
        If a recognized filename has invalid geographic coordinates or spacing.
    """
    filename = path.replace("\\", "/").rsplit("/", 1)[-1]
    match = re.fullmatch(r"srtm_(\d{2})_(\d{2})\.tif", filename, re.IGNORECASE)
    if match:
        west = -180 + 5 * (int(match[1]) - 1)
        south = 60 - 5 * int(match[2])
        return TileInfo(path, west, west + 5, south, south + 5, "egm96", 90)

    match = re.fullmatch(r"([ns]\d{2})([ew]\d{3})(?:\..*)?\.hgt", filename, re.IGNORECASE)
    datum: Datum = "egm96"
    resolution = 30.0
    width = 1
    if match:
        lat_string, lon_string = match[1], match[2]
        with gdal.ExceptionMgr(useExceptions=True), gdal.Open(path) as dataset:
            resolution = 108000 / (dataset.RasterYSize - 1)
    elif match := re.search(r"(?:^|/)([ew]\d{3})/([ns]\d{2})\.dt([012])$", path.replace("\\", "/"), re.IGNORECASE):
        lon_string, lat_string = match[1], match[2]
        resolution = (900, 90, 30)[int(match[3])]
    elif match := re.fullmatch(r"TDM1_[IFH]?DEM__(\d{2})_([ns]\d{2})([ew]\d{3})_DEM\.tif", filename, re.IGNORECASE):
        lat_string, lon_string = match[2], match[3]
        datum = "wgs84"
        resolution = int(match[1]) * 3
        latitude = int(lat_string[1:])
        width = 4 if latitude >= 80 else 2 if latitude >= 60 else 1
    elif match := re.fullmatch(r"([ew]\d{3})([ns]\d{2})_DSM\.tif", filename, re.IGNORECASE):
        lon_string, lat_string = match[1], match[2]
        datum = "egm2008"
        resolution = 12
    elif match := re.fullmatch(
        r"Copernicus_DSM_(?:COG_)?(\d{2})_([ns]\d{2})_\d{2}_([ew]\d{3})_\d{2}_DEM\.(?:tif|dt[012])", filename, re.IGNORECASE
    ):
        lat_string, lon_string = match[2], match[3]
        datum = "egm2008"
        resolution = int(match[1]) * 3
    else:
        return None

    south = int(lat_string[1:]) * (1 if lat_string[0].upper() == "N" else -1)
    west = int(lon_string[1:]) * (1 if lon_string[0].upper() == "E" else -1)
    if not (-180 <= west < 180 and -90 <= south < 90 and resolution > 0):
        raise ValueError(f"Invalid DEM coordinates or spacing in filename: {filename}")
    return TileInfo(path, west, min(west + width, 180), south, south + 1, datum, resolution)


def discover_tiles(folder: str, *, exclude_directories: tuple[str, ...] = ()) -> tuple[TileInfo, ...]:
    """Scan one local dataset path, including ZIP/TAR rasters and mapping.csv.

    DTED duplicates are ordered by resolution. Directory order is deterministic;
    priority between different dataset paths is controlled by the caller.

    Parameters
    ----------
    folder : str
        Existing directory to scan recursively.
    exclude_directories : tuple of str, default=()
        Top-level directory names to omit from the scan.

    Returns
    -------
    tuple of TileInfo
        Discovered tiles ordered by nominal resolution.

    Raises
    ------
    ValueError
        If folder is absent or a recognized archive has no supported raster.
    """
    if not os.path.isdir(folder):
        raise ValueError(f"Local DEM path must be an existing directory: {folder}")
    mappings: dict[str, tuple[str, str]] = {}
    filenames = []
    for root, directories, files in os.walk(folder):
        if root == folder:
            directories[:] = [name for name in directories if name not in exclude_directories]
        directories.sort()
        for filename in sorted(files):
            path = os.path.join(root, filename)
            if filename.lower() == "mapping.csv":
                with open(path, newline="", encoding="utf-8-sig") as stream:
                    rows = csv.reader(stream, delimiter=";")
                    next(rows, None)
                    for row in rows:
                        mappings[row[0]] = (row[1], row[2])
            else:
                filenames.append(path)

    tiles = []
    for path in filenames:
        extension = os.path.splitext(path)[1].lower()
        if extension not in {".zip", ".tar"}:
            info = identify_tile(path)
            if info is not None:
                tiles.append(info)
            continue
        tiles.extend(archive_tiles(path, mappings.get(os.path.basename(path))))
    return tuple(sorted(tiles, key=lambda tile: tile.resolution))


def archive_tiles(path: str, mapping: tuple[str, str] | None = None) -> tuple[TileInfo, ...]:
    """Discover supported rasters in ZIP/TAR archives without extracting files.

    Parameters
    ----------
    path : str
        ZIP or TAR archive path.
    mapping : tuple of str or None, default=None
        Latitude and longitude names for legacy DEM delivery archives.

    Returns
    -------
    tuple of TileInfo
        Raster metadata with GDAL virtual paths. Mapping supplies Copernicus
        latitude/longitude names for legacy delivery archives when necessary.

    Raises
    ------
    ValueError
        If a recognized DEM archive contains no supported raster.
    """
    extension = os.path.splitext(path)[1].lower()
    if extension == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = sorted(member.filename for member in archive.infolist() if not member.is_dir())
    else:
        with tarfile.open(path) as archive:
            members = sorted(member.name for member in archive.getmembers() if member.isfile())
    tiles = []
    for member in members:
        virtual_path = f"/vsi{extension[1:]}/{path.replace(os.sep, '/')}/{member}"
        info = identify_tile(virtual_path)
        if (
            info is None
            and re.fullmatch(r"srtm_\d{2}_\d{2}\.zip", os.path.basename(path), re.IGNORECASE)
            and member.lower().endswith(".tif")
        ):
            info = identify_tile(os.path.splitext(path)[0] + ".tif")
            if info is not None:
                info = replace(info, path=virtual_path)
        if info is None and mapping is not None and member.lower().endswith((".tif", ".dt0", ".dt1", ".dt2")):
            match = re.fullmatch(r"DEM1_SAR_D[TG]E_(\d{2})_.*\.DEM\.(?:zip|tar)", os.path.basename(path), re.IGNORECASE)
            if match:
                latitude, longitude = mapping
                info = identify_tile(f"Copernicus_DSM_10_{latitude}_00_{longitude}_00_DEM.tif")
                if info is not None:
                    info = replace(info, path=virtual_path, resolution=float(match[1]))
        if info is not None:
            tiles.append(info)
    recognized_archive = re.match(r"(?:[ns]\d{2}[ew]\d{3}|srtm_|TDM1_|Copernicus_DSM_|DEM1_SAR_)", os.path.basename(path), re.IGNORECASE)
    if recognized_archive and not tiles:
        raise ValueError(f"No supported DEM raster found in archive: {path}")
    return tuple(tiles)


def index_tiles(tiles: tuple[TileInfo, ...]) -> dict[tuple[int, int], TileInfo]:
    """Index tiles by degree cell, retaining the first tile for each cell.

    Parameters
    ----------
    tiles : tuple of TileInfo
        Tiles to index by the degree cells in their nominal bounds.

    Returns
    -------
    dict of tuple[int, int] to TileInfo
        Tile metadata indexed by southwest degree-cell coordinates.
    """
    cells = {}
    for tile in tiles:
        for lat in range(math.floor(tile.south), math.ceil(tile.north)):
            for lon in range(math.floor(tile.west), math.ceil(tile.east)):
                cells.setdefault((lon, lat), tile)
    return cells
