<div align="center">
    <p>
        <img src="https://raw.githubusercontent.com/Haight3/Altira/refs/heads/main/resources/images/logo.jfif" width="75%">
    </p>

<h2 align="center">Altira v-2026.9.0</h2>
<h4 align="center">Image-driven DEM acquisition and elevation queries.</h4>

<p align="center">
  <a href="#overview">Overview</a> &bull;
  <a href="#installation">Installation</a> &bull;
  <a href="#dem-usage">Quick Start</a> &bull;
  <a href="#documentation">Documentation</a> &bull;
  <a href="#development">Development</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/altira/">
    <img src="https://img.shields.io/pypi/v/altira.svg" alt="PyPI">
  </a>
  <a href="https://github.com/Haight3/Altira/actions/workflows/ci.yml">
    <img src="https://github.com/Haight3/Altira/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="https://github.com/Haight3/Altira/actions/workflows/validate-release-meta.yaml">
    <img src="https://github.com/Haight3/Altira/actions/workflows/validate-release-meta.yaml/badge.svg" alt="Validate Release Metadata">
  </a>
  <a href="https://github.com/Haight3/Altira/actions/workflows/deploy.yaml">
    <img src="https://github.com/Haight3/Altira/actions/workflows/deploy.yaml/badge.svg" alt="Deployment">
  </a>
</p>
</div>


# Overview

Altira selects DEM tiles from georeferenced rasters, downloads Copernicus,
ALOS, or SRTM data, and provides elevation interpolation, height statistics, and local
DEM support. All elevation arrays and queries use WGS84 ellipsoidal meters.

# Installation

Use the `altira` Conda environment for GDAL and PROJ. From this checkout:

```powershell
conda env create -f resources/envs/altira.yml
conda activate altira
python -m pip install -e .
```

The base package supports georeferenced raster paths, DEM downloads, coordinate
queries, and local DEMs. GDAL reads raster georeferencing directly.

# DEM usage

```python
from altira import Dem

dem = Dem(cache_dir="D:/DEM", local_paths=(), resolution=30)
tiles = dem.preload_image("D:/Images/scene.tif")

heights = dem.interpolate_heights([13.3, 13.31], [52.5, 52.51])
minimum, maximum, average = dem.get_height_bounds(
    13.3, 13.31, 52.5, 52.51, compute_avg_height=True
)
```

`preload_image` returns a tuple of `DemTile` objects with `info`, `heights`, and
`transform` attributes. `info.path` identifies the unchanged native source
raster; `heights` is a float32 array converted to ellipsoidal meters. Raster
paths must provide an affine transform and CRS. GDAL reads these directly,
including projected and rotated grids.

For footprints supplied by a caller, load DEM tiles using explicit WGS84 bounds:

```python
tiles = dem.preload_dem_tiles(west=13.3, east=13.31, south=52.5, north=52.51)
```

Use `west > east` for bounds crossing the antimeridian. Product metadata loading
and geocoding are the caller's responsibility.

```powershell
altira download "D:/Images/scene.tif" --cache-dir "D:/DEM"
altira download "D:/Images/scene.tif" --cache-dir "D:/DEM" --source alos-ellipsoidal
```

Select the online dataset explicitly with `source`:


| Source                 | Native resolution | Native vertical datum |
| ------------------------ | ------------------- | ----------------------- |
| `copernicus` (default) | 30 or 90 m        | EGM2008               |
| `alos`                 | 30 m              | EGM96                 |
| `alos-ellipsoidal`     | 30 m              | WGS84 ellipsoid       |
| `srtm`                 | 30 or 90 m        | EGM96                 |
| `srtm-ellipsoidal`     | 30 m              | WGS84 ellipsoid       |

```python
dem = Dem(cache_dir="D:/DEM", source="alos-ellipsoidal", resolution=30)
tiles = dem.preload_image("D:/Images/scene.tif")
```

ALOS and SRTM use [OpenTopography's anonymous bulk storage](https://opentopography.org/developers),
without an account or API key. Published VRT indexes determine coverage; only
selected native tiles are downloaded. Ellipsoidal variants skip geoid conversion.
These are OpenTopography's published mirrors, which may differ in version from
the original producers' current releases. ALOS is a surface model, so elevations
can include vegetation and buildings. See the source dataset pages for attribution:
[ALOS](https://portal.opentopography.org/raster?opentopoID=OTALOS.112016.4326.2),
[ALOS Ellipsoidal](https://portal.opentopography.org/raster?opentopoID=OTALOS.082017.4326.1),
[SRTM](https://portal.opentopography.org/raster?opentopoID=OTSRTM.042013.4326.1),
and [SRTM Ellipsoidal](https://portal.opentopography.org/raster?opentopoID=OTSRTM.082016.4326.1).

Local directories take priority in their supplied order, with the finest
resolution preferred within each directory. Supported formats include SRTM
HGT, CGIAR SRTM, DTED, TanDEM-X, edited TanDEM-X, Copernicus, and ZIP/TAR
deliveries. Coverage gaps are logged, without switching source or resolution.
Interpolation fills unavailable or nodata posts with `avg_height=0`; use
`avg_height=float("nan")` to retain gaps. Raster and network failures raise.

See [the usage guide](docs/usage.rst) for cache, datum, and statistics details.

# Documentation

The [documentation site](https://altira.readthedocs.io/) includes the usage guide
and API reference. The documentation source is in [`docs/`](docs/).

# Development

Install the development dependencies:

```cmd
> pip install -e .[dev]
```

Run the core test suite directly with `pytest`:

```cmd
> pytest
```

Run linting and formatting with Ruff:

```cmd
> python -m ruff check --fix .
> python -m ruff format .
```

To include coverage:

```cmd
> pytest --cov --cov-report=term-missing
```
