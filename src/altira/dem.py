"""Tile-based DEM acquisition, interpolation, and ellipsoidal height statistics.

Copyright (C) 2026
"""

from __future__ import annotations

import logging
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

from .coverage import degree_cells, split_bounds, tile_name
from .datasets import TileInfo, discover_tiles, index_tiles
from .image import image_bounds
from .provider import Source, create_provider
from .raster import GeoTransform, Raster, bilinear_values, read_raster
from .vertical import convert_heights

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import ArrayLike, NDArray

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class DemTile:
    """A source tile's metadata, sample grid, and WGS84 ellipsoidal heights.

    info.path points to the unchanged source raster in its native vertical
    datum. heights contains float32 ellipsoidal meters, with NaN for nodata.

    Attributes
    ----------
    info : TileInfo
        Metadata and path for the unchanged source raster.
    heights : ndarray
        Two-dimensional float32 grid of WGS84 ellipsoidal elevations.
    transform : GeoTransform
        Pixel-edge geotransform for the elevation grid.
    datum : {"wgs84"}
        Vertical datum of ``heights``.
    """

    info: TileInfo
    heights: NDArray[np.float32]
    transform: GeoTransform
    datum: Literal["wgs84"] = "wgs84"


class Dem:
    """Persistent local dataset index, online provider, and bounded LRU tile cache.

    Local directories have priority in their supplied order; within a directory
    the finest nominal resolution wins. The selected source serves remaining cells.
    All elevation queries return WGS84 ellipsoidal meters. Missing cells are
    logged once per instance; interpolation uses the explicit avg_height for
    their samples. Network, raster, and datum-conversion failures raise errors.

    Parameters
    ----------
    cache_dir : str
        Persistent directory for remote rasters, catalogs, and geoid grids.
    local_paths : sequence of str, default=()
        Existing local DEM directories, ordered by priority.
    source : Source, default="copernicus"
        Online dataset: copernicus, alos, alos-ellipsoidal, srtm, or srtm-ellipsoidal.
    resolution : {30, 90}, default=30
        Native online resolution. Only Copernicus and SRTM support 90 meters.
        Neither source nor resolution changes automatically for coverage gaps.
    max_cache_size_mb : float, default=500
        Maximum cached elevation-array memory in MiB. Zero disables memory caching.
        Arrays retained by callers of preload methods are outside this limit.
    """

    def __init__(
        self,
        *,
        cache_dir: str,
        local_paths: Sequence[str] = (),
        source: Source = "copernicus",
        resolution: Literal[30, 90] = 30,
        max_cache_size_mb: float = 500,
    ) -> None:
        """Index local datasets and initialize a lazy online provider.

        Parameters
        ----------
        cache_dir : str
            Persistent directory for remote rasters and geoid grids.
        local_paths : sequence of str, default=()
            Local DEM directories ordered by priority.
        source : Source, default="copernicus"
            Explicit online dataset to use for cells without local coverage.
        resolution : {30, 90}, default=30
            Native DEM resolution supported by the selected source.
        max_cache_size_mb : float, default=500
            Maximum in-memory elevation-array cache size in MiB.

        Raises
        ------
        ValueError
            If the cache limit, source, or source/resolution combination is invalid.
        """
        if not math.isfinite(max_cache_size_mb) or max_cache_size_mb < 0:
            raise ValueError("max_cache_size_mb must be finite and nonnegative.")
        self.cache_dir = cache_dir
        self.max_cache_size_mb = max_cache_size_mb
        self.provider = create_provider(cache_dir=cache_dir, source=source, resolution=resolution)
        self.local_tiles: dict[tuple[int, int], TileInfo] = {}
        self.tile_priority: dict[str, int] = {}
        for folder in local_paths:
            tiles = discover_tiles(folder)
            for tile in tiles:
                self.tile_priority.setdefault(tile.path, len(self.tile_priority))
            for cell, tile in index_tiles(tiles).items():
                self.local_tiles.setdefault(cell, tile)
        self.tile_cache: OrderedDict[str, DemTile] = OrderedDict()
        self.remote_paths: set[str] = set()
        self.missing_cells: set[tuple[int, int]] = set()

    @property
    def cache_size_mb(self) -> float:
        """Current cached elevation-array memory in MiB."""
        return sum(tile.heights.nbytes for tile in self.tile_cache.values()) / (1024 * 1024)

    def tiles_for_cells(self, cells: Sequence[tuple[int, int]]) -> tuple[TileInfo, ...]:
        """Select one preferred dataset per degree cell and report uncovered cells.

        Parameters
        ----------
        cells : sequence of tuple[int, int]
            Southwest longitude and latitude coordinates of degree cells.

        Returns
        -------
        tuple of TileInfo
            Unique selected tiles in dataset-priority order.
        """
        tiles = {}
        for lon, lat in cells:
            info = self.local_tiles.get((lon, lat))
            if info is None:
                info = self.provider.find_tile(lon, lat)
                if info is not None:
                    self.remote_paths.add(info.path)
            if info is not None:
                tiles[info.path] = info
            elif (lon, lat) not in self.missing_cells:
                logger.warning("No DEM tile available for %s (%s).", tile_name(lon, lat), self.provider.label)
                self.missing_cells.add((lon, lat))
        return tuple(sorted(tiles.values(), key=lambda info: self.tile_priority.get(info.path, len(self.tile_priority))))

    def find_tiles(self, west: float, east: float, south: float, north: float) -> tuple[TileInfo, ...]:
        """Find preferred local/online tile metadata intersecting geographic bounds.

        Parameters
        ----------
        west, east, south, north : float
            Geographic limits in degrees, ordered as west, east, south, north.

        Returns
        -------
        tuple of TileInfo
            Available tiles in dataset-priority order, without raster downloads.
        """
        return self.tiles_for_cells(degree_cells(west, east, south, north))

    def load_tile(self, info: TileInfo) -> DemTile:
        """Read and convert a tile, reusing or updating the bounded LRU cache.

        Parameters
        ----------
        info : TileInfo
            Metadata for the source raster to load.

        Returns
        -------
        DemTile
            Ellipsoidal elevations and source metadata.

        Raises
        ------
        ValueError
            If the raster grid does not match its named geographic coverage.
        """
        if info.path in self.tile_cache:
            self.tile_cache.move_to_end(info.path)
            return self.tile_cache[info.path]
        if info.path in self.remote_paths:
            self.provider.download_tile(info)
        raster = read_raster(info.path)
        transform = raster.transform
        height, width = raster.values.shape
        limits = (
            (transform[0] + 0.5 * transform[1], info.west, transform[1]),
            (transform[0] + (width - 0.5) * transform[1], info.east, transform[1]),
            (transform[3] + 0.5 * transform[5], info.north, -transform[5]),
            (transform[3] + (height - 0.5) * transform[5], info.south, -transform[5]),
        )
        if any(abs(actual - expected) > spacing + 1e-8 for actual, expected, spacing in limits):
            raise ValueError(f"DEM raster grid does not match its named geographic coverage: {info.path}")
        convert_heights(raster, source_datum=info.source_datum, cache_dir=self.cache_dir)
        tile = DemTile(info=info, heights=raster.values, transform=raster.transform)
        self.tile_cache[info.path] = tile
        while self.cache_size_mb > self.max_cache_size_mb:
            self.tile_cache.popitem(last=False)
        return tile

    def preload_dem_tiles(self, west: float, east: float, south: float, north: float) -> tuple[DemTile, ...]:
        """Download, convert, and load all available tiles covering geographic bounds.

        Parameters
        ----------
        west, east, south, north : float
            Geographic limits in degrees, ordered as west, east, south, north.

        Returns
        -------
        tuple of DemTile
            Loaded available tiles; missing cells are logged.
        """
        return tuple(self.load_tile(info) for info in self.find_tiles(west, east, south, north))

    def preload_image(self, image: str) -> tuple[DemTile, ...]:
        """Load tiles covering one georeferenced raster.

        Parameters
        ----------
        image : str
            Raster path with an affine transform and CRS. For product metadata,
            pass geographic bounds to ``preload_dem_tiles`` instead.

        Returns
        -------
        tuple of DemTile
            Loaded tiles selected from the image's geographic footprint.
        """
        return self.preload_dem_tiles(*image_bounds(image))

    def tiles_at(self, lon: NDArray[np.float64], lat: NDArray[np.float64]) -> tuple[TileInfo, ...]:
        """Select preferred tiles for coordinate arrays without loading their rasters.

        Parameters
        ----------
        lon, lat : ndarray
            Matching arrays of geographic coordinates.

        Returns
        -------
        tuple of TileInfo
            Available tiles covering the queried degree cells.
        """
        longitude_cells = np.floor(lon).astype(np.int64).ravel()
        latitude_cells = np.minimum(np.floor(lat), 89).astype(np.int64).ravel()
        cells = np.unique(np.column_stack((longitude_cells, latitude_cells)), axis=0)
        return self.tiles_for_cells(tuple((int(left), int(bottom)) for left, bottom in cells))

    def read_posts(self, lon: NDArray[np.float64], lat: NDArray[np.float64]) -> NDArray[np.float32]:
        """Read nearest valid DEM posts when bilinear neighborhoods cross tile edges.

        Parameters
        ----------
        lon, lat : ndarray
            Matching arrays of geographic sample coordinates.

        Returns
        -------
        ndarray
            Float32 post values, with NaN for invalid/unavailable samples.
        """
        lon = (lon + 180) % 360 - 180
        lat = np.clip(lat, -90, 90)
        result = np.full(lon.shape, np.nan, dtype=np.float32)
        assigned = np.zeros(lon.shape, dtype=bool)
        infos = self.tiles_at(lon, lat)
        for include_edges in (False, True):
            for info in infos:
                sample_lon = np.where(include_edges & (lon == -180) & (info.east == 180), 180, lon)
                mask = (sample_lon >= info.west) & (lat >= info.south) & ~assigned
                if include_edges:
                    mask &= (sample_lon <= info.east) & (lat <= info.north)
                else:
                    mask &= (sample_lon < info.east) & ((lat < info.north) | ((lat == 90) & (info.north == 90)))
                if not mask.any():
                    continue
                tile = self.load_tile(info)
                x, y = Raster(tile.heights, tile.transform).pixel_coordinates(sample_lon[mask], lat[mask])
                columns = np.rint(x).astype(np.int64)
                rows = np.rint(y).astype(np.int64)
                valid = (columns >= 0) & (columns < tile.heights.shape[1]) & (rows >= 0) & (rows < tile.heights.shape[0])
                positions = np.flatnonzero(mask)[valid]
                result.ravel()[positions] = tile.heights[rows[valid], columns[valid]]
                assigned.ravel()[positions] = True  # A nodata post stays nodata even if another tile overlaps it.
            if assigned.all():
                return result
            if not include_edges:
                # AWS removes southern rows: the post at an integer latitude may
                # belong to the tile below its nominal containing degree cell.
                neighbors = []
                for longitude, latitude in zip(lon[~assigned], lat[~assigned], strict=True):
                    cell_lon, cell_lat = math.floor(longitude), min(math.floor(latitude), 89)
                    on_lon = abs(longitude - round(longitude)) < 1e-8
                    on_lat = abs(latitude - round(latitude)) < 1e-8
                    if on_lat and cell_lat > -90:
                        neighbors.append((cell_lon, cell_lat - 1))
                    previous_lon = cell_lon - 1 if cell_lon > -180 else 179
                    if on_lon:
                        neighbors.append((previous_lon, cell_lat))
                    if on_lon and on_lat and cell_lat > -90:
                        neighbors.append((previous_lon, cell_lat - 1))
                infos = self.tiles_for_cells(tuple(dict.fromkeys(neighbors)))
        return result

    def interpolate_heights(self, lon: ArrayLike, lat: ArrayLike, avg_height: float = 0) -> NDArray[np.float32]:
        """Bilinearly interpolate WGS84 ellipsoidal elevations with the input shape.

        Longitude and latitude must have matching shapes, finite values, and
        valid geographic ranges. Invalid or unavailable contributing posts use
        avg_height. A NaN fill
        may be supplied to preserve missing elevations.

        Parameters
        ----------
        lon, lat : array-like
            Matching arrays or array-like values of longitude and latitude in degrees.
        avg_height : float, default=0
            Fill value for invalid or unavailable contributing posts. NaN preserves
            missing elevations; infinity is invalid.

        Returns
        -------
        ndarray
            Float32 ellipsoidal meters with the longitude/latitude input shape.

        Raises
        ------
        ValueError
            If coordinate shapes differ, coordinates are invalid, or the fill is infinite.
        """
        longitude = np.asarray(lon, dtype=np.float64)
        latitude = np.asarray(lat, dtype=np.float64)
        if longitude.shape != latitude.shape:
            raise ValueError("Longitude and latitude arrays must have the same shape.")
        if not np.isfinite(longitude).all() or not np.isfinite(latitude).all():
            raise ValueError("Longitude and latitude values must be finite.")
        if np.any(np.abs(longitude) > 180) or np.any(np.abs(latitude) > 90):
            raise ValueError("Expected longitude in [-180, 180] and latitude in [-90, 90].")
        if math.isinf(avg_height):
            raise ValueError("avg_height must be finite or NaN.")
        result = np.full(longitude.shape, avg_height, dtype=np.float32)
        if not longitude.size:
            return result
        longitude = np.where(longitude == 180, -180.0, longitude)
        assigned = np.zeros(longitude.shape, dtype=bool)
        for info in self.tiles_at(longitude, latitude):
            mask = (longitude >= info.west) & (longitude < info.east) & (latitude >= info.south)
            mask &= (latitude < info.north) | ((latitude == 90) & (info.north == 90))
            mask &= ~assigned
            if not mask.any():
                continue
            assigned |= mask
            tile = self.load_tile(info)
            x, y = Raster(tile.heights, tile.transform).pixel_coordinates(longitude[mask], latitude[mask])
            x = np.where(np.abs(x - np.rint(x)) < 1e-8, np.rint(x), x)
            y = np.where(np.abs(y - np.rint(y)) < 1e-8, np.rint(y), y)
            columns, rows = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
            dx, dy = x - columns, y - rows
            samples = []
            weights = ((1 - dx) * (1 - dy), dx * (1 - dy), (1 - dx) * dy, dx * dy)
            for (column_delta, row_delta), weight in zip(((0, 0), (1, 0), (0, 1), (1, 1)), weights, strict=True):
                sample_x, sample_y = columns + column_delta, rows + row_delta
                inside = (sample_x >= 0) & (sample_x < tile.heights.shape[1]) & (sample_y >= 0) & (sample_y < tile.heights.shape[0])
                values = np.full(x.shape, np.nan, dtype=np.float32)
                values[inside] = tile.heights[sample_y[inside], sample_x[inside]]
                outside = ~inside & (weight > 1e-12)
                if outside.any():
                    transform = tile.transform
                    post_lon = transform[0] + (sample_x[outside] + 0.5) * transform[1]
                    post_lat = transform[3] + (sample_y[outside] + 0.5) * transform[5]
                    values[outside] = self.read_posts(post_lon, post_lat)
                samples.append(values)
            result[mask] = bilinear_values(tuple(samples), dx, dy, avg_height)
        return result

    def get_height_bounds(
        self,
        west: float,
        east: float,
        south: float,
        north: float,
        compute_avg_height: bool = False,
    ) -> tuple[float, float, float | None]:
        """Return min/max and optional sample-weighted mean within geographic bounds.

        Only valid sample centers inside the region are counted. Dataset
        priority is applied per cell, so overlaps and shared posts are not
        double-counted. No valid samples raises ValueError.

        Parameters
        ----------
        west, east, south, north : float
            Geographic limits in degrees, ordered as west, east, south, north.
        compute_avg_height : bool, default=False
            Whether to calculate the sample-weighted mean.

        Returns
        -------
        tuple[float, float, float or None]
            Ellipsoidal minimum, maximum, and optional sample-weighted mean.

        Raises
        ------
        ValueError
            If no valid DEM sample centers lie inside the region.
        """
        regions = split_bounds(west, east, south, north)
        cells = degree_cells(west, east, south, north)
        infos = self.tiles_for_cells(cells)
        ownership = {}
        for cell in cells:
            ownership[cell] = next((info.path for info in infos if info.covers(*cell)), None)
        minimum, maximum, total, count = math.inf, -math.inf, 0.0, 0
        for info in infos:
            tile = self.load_tile(info)
            height, width = tile.heights.shape
            transform = tile.transform
            lon = transform[0] + (np.arange(width) + 0.5) * transform[1]
            lat = transform[3] + (np.arange(height) + 0.5) * transform[5]
            selected = np.zeros(tile.heights.shape, dtype=bool)
            for left, right, bottom, top in regions:
                longitude_cells = np.floor(lon).astype(np.int64)
                # North-to-south grids retain the northern boundary in the tile
                # below it. Assign shared latitude posts once to that cell.
                latitude_cells = np.minimum(np.ceil(lat) - 1, 89).astype(np.int64)
                latitude_cells[lat == bottom] = min(math.floor(bottom), 89)
                if left != right and right == math.floor(right):
                    longitude_cells[lon == right] -= 1
                columns = (lon >= left) & (lon <= right)
                rows = (lat >= bottom) & (lat <= top)
                for (cell_lon, cell_lat), owner in ownership.items():
                    if owner == info.path:
                        selected |= (rows & (latitude_cells == cell_lat))[:, None] & (columns & (longitude_cells == cell_lon))[None, :]
            values = tile.heights[selected & np.isfinite(tile.heights)]
            if values.size:
                minimum = min(minimum, float(values.min()))
                maximum = max(maximum, float(values.max()))
                count += values.size
                if compute_avg_height:
                    total += float(values.sum(dtype=np.float64))
        if not count:
            raise ValueError("No valid DEM samples available inside the specified region.")
        return minimum, maximum, total / count if compute_avg_height else None

    def get_dem_resolution(self, west: float, east: float, south: float, north: float) -> float:
        """Return the finest selected nominal resolution, raising if no tile exists.

        Parameters
        ----------
        west, east, south, north : float
            Geographic limits in degrees, ordered as west, east, south, north.

        Returns
        -------
        float
            Finest available nominal resolution in meters.

        Raises
        ------
        ValueError
            If no DEM tiles cover the region.
        """
        tiles = self.find_tiles(west, east, south, north)
        if not tiles:
            raise ValueError("No DEM tiles available for the specified region.")
        return min(info.resolution for info in tiles)
