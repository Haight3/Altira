"""Select geographic degree cells from WGS84 bounds, including wrapped longitudes.

Copyright (C) 2026
"""

import math


def split_bounds(west: float, east: float, south: float, north: float) -> tuple[tuple[float, float, float, float], ...]:
    """Validate WGS84 bounds and split an antimeridian crossing into two regions.

    Bounds use (west, east, south, north). Equal limits describe a point or line;
    west greater than east describes an antimeridian crossing.

    Parameters
    ----------
    west, east, south, north : float
        Geographic limits in degrees, ordered as west, east, south, north.

    Returns
    -------
    tuple of tuple[float, float, float, float]
        One or two non-wrapped geographic regions.

    Raises
    ------
    ValueError
        If limits are non-finite, out of geographic range, or latitudes reversed.
    """
    if not all(math.isfinite(value) for value in (west, east, south, north)):
        raise ValueError("Geographic bounds must be finite.")
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError("Expected longitude in [-180, 180] and -90 <= south <= north <= 90.")
    if west == east == 180:
        return ((-180.0, -180.0, south, north),)
    if west > east:
        regions = []
        if west < 180:
            regions.append((west, 180.0, south, north))
        if east > -180:
            regions.append((-180.0, east, south, north))
        return tuple(regions) or ((-180.0, -180.0, south, north),)
    return ((west, east, south, north),)


def degree_cells(west: float, east: float, south: float, north: float) -> tuple[tuple[int, int], ...]:
    """Return intersected cells without boundary-only neighbors.

    Parameters
    ----------
    west, east, south, north : float
        Geographic limits in degrees, ordered as west, east, south, north.

    Returns
    -------
    tuple of tuple[int, int]
        Unique southwest (longitude, latitude) cell coordinates.
    """
    cells = []
    for left, right, bottom, top in split_bounds(west, east, south, north):
        first_lat = min(math.floor(bottom), 89)
        last_lat = max(math.ceil(top) - 1, first_lat)
        first_lon = math.floor(left)
        last_lon = max(math.ceil(right) - 1, first_lon)
        cells.extend((lon, lat) for lat in range(first_lat, last_lat + 1) for lon in range(first_lon, last_lon + 1))
    return tuple(dict.fromkeys(cells))


def tile_name(lon: int, lat: int) -> str:
    """Return the canonical southwest cell name.

    Parameters
    ----------
    lon, lat : int
        Southwest longitude and latitude cell coordinates in degrees.

    Returns
    -------
    str
        Latitude/longitude name such as N52E013.
    """
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
