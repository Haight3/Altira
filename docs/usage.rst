=====
Usage
=====

Image-driven DEM selection
--------------------------

Use the ``altira`` Conda environment described in the README and install the base
package with ``pip install -e .``. Altira accepts georeferenced raster paths or
explicit geographic bounds supplied by the caller.

.. code-block:: python

    from altira import Dem

    dem = Dem(
        cache_dir="D:/DEM",
        local_paths=("D:/LocalDEM",),
        source="copernicus",
        resolution=30,
        max_cache_size_mb=500,
    )
    tiles = dem.preload_image("D:/Images/scene.tif")

``preload_image`` accepts a string raster path with an affine geotransform and
CRS and uses GDAL directly. Projected edges are densified when transforming to WGS84;
rotated grids use a conservative envelope that may select additional DEM tiles.
Antimeridian coverage is preserved. No footprint is invented for unlocated rasters.

Product directories, metadata files, and rasters without an affine transform
and CRS raise ``ValueError``. Product loading and metadata geocoding belong to
the caller. Once a geographic footprint is available, pass its bounds directly:

.. code-block:: python

    tiles = dem.preload_dem_tiles(west=13.3, east=13.31, south=52.5, north=52.51)

Bounds use WGS84 degrees; ``west > east`` preserves an antimeridian crossing.

The returned tuple contains available ``DemTile`` objects. Each exposes:

* ``info``: source path, nominal bounds, native vertical datum, and resolution.
* ``heights``: float32 WGS84 ellipsoidal meters, with NaN for nodata.
* ``transform``: the six native GDAL geotransform coefficients.
* ``datum``: ``"wgs84"``, describing the in-memory heights.

Tile arrays retain the native raster sampling grid. The source file at
``tile.info.path`` retains its original vertical datum. No mosaic or resampled
output file is created.

Elevation queries
-----------------

.. code-block:: python

    heights = dem.interpolate_heights([13.3, 13.31], [52.5, 52.51], avg_height=0)
    minimum, maximum, average = dem.get_height_bounds(
        13.3, 13.31, 52.5, 52.51, compute_avg_height=True
    )
    resolution = dem.get_dem_resolution(13.3, 13.31, 52.5, 52.51)
    tiles = dem.preload_dem_tiles(13.3, 13.31, 52.5, 52.51)

All bound arguments use ``(west, east, south, north)`` in WGS84 degrees.
``west > east`` denotes an antimeridian crossing. Longitude/latitude interpolation
arrays must have matching shapes; the float32 result preserves that shape.
Bilinear neighborhoods read neighboring tiles when necessary.

Missing cells are logged once per ``Dem`` instance. Interpolation substitutes
``avg_height`` for missing or nodata contributing posts; pass ``float("nan")``
to preserve these gaps. Height statistics count only valid sample centers within
the region, apply local dataset priority, and avoid counting shared posts twice.
The optional mean is weighted by sample count. Without ``compute_avg_height=True``,
the third return value is ``None``. Statistics raise ``ValueError`` when no valid
sample centers exist; resolution queries raise when no tiles are available.
Partial coverage produces available statistics and a warning for missing cells.

Local datasets, downloads, and caching
------------------------------------

Supported local formats are SRTM HGT, CGIAR SRTM GeoTIFF, DTED levels 0/1/2,
TanDEM-X, edited TanDEM-X, and Copernicus GeoTIFF/DTED. Conventional dataset
filenames identify coverage and vertical datum. ZIP/TAR rasters are read through
GDAL without extraction; legacy Copernicus deliveries can use ``mapping.csv``.

Local directories take priority in their supplied order. Existing user-organized
tiles in ``cache_dir`` (for example, ``D:/DEM/E132/*.tif``) are indexed next.
Provider-managed directories retain their source-specific catalog selection.
Within a directory, the finest nominal resolution wins. Remaining cells use public Copernicus
GLO-30 by default. Set ``resolution=90`` explicitly for GLO-90; unavailable
GLO-30 cells never cause an automatic switch to GLO-90. The local index is built
at construction; construct a new ``Dem`` after adding local data.

EGM96 sources use the NGA EGM96 geoid grid; Copernicus and edited TanDEM-X use
the NGA EGM2008 grid. Native TanDEM-X ellipsoidal heights need no conversion.
Required grids download from the PROJ CDN and are resampled to the DEM's actual
grid before applying ``ellipsoidal height = orthometric height + geoid height``.
HTTP, invalid raster, and failed datum-conversion errors propagate.

New Copernicus downloads are grouped by longitude under
``cache_dir/copernicus-30m/E132`` or ``cache_dir/copernicus-90m/E132``.
Catalogs remain in the product directory; existing tiles directly in that
directory are reused without moving them. Existing valid tiles are reused,
and only missing tiles are downloaded. Geoid grids live under ``cache_dir/geoid``.
Downloads publish validated files atomically. The in-memory LRU limit covers
cached elevation arrays in MiB. Zero disables it, and oversized tiles are
returned without being retained. Arrays kept by callers of preload methods
are outside this limit.

Selecting an online dataset
---------------------------

``source`` selects a product explicitly. All returned elevations remain WGS84
ellipsoidal meters, regardless of the downloaded source's vertical datum.

.. list-table:: Supported online datasets
    :header-rows: 1

    * - Source
      - Native resolution
      - Native height datum
    * - ``copernicus`` (default)
      - 30 or 90 m
      - EGM2008
    * - ``alos``
      - 30 m
      - EGM96
    * - ``alos-ellipsoidal``
      - 30 m
      - WGS84 ellipsoid
    * - ``srtm``
      - 30 or 90 m
      - EGM96
    * - ``srtm-ellipsoidal``
      - 30 m
      - WGS84 ellipsoid

.. code-block:: python

    dem = Dem(cache_dir="D:/DEM", source="alos-ellipsoidal", resolution=30)
    tiles = dem.preload_image("D:/Images/scene.tif")

ALOS and SRTM use anonymous OpenTopography bulk storage. The Global Datasets API
is not used and no account or API key is required. The published VRT catalog is
cached once; tile references supply exact available coverage without fetching
the global mosaic. Only selected raster files are downloaded. Product caches
live under ``cache_dir/opentopography/<dataset>``:

* ``AW3D30`` and ``AW3D30_E`` for the two ALOS variants.
* ``SRTM_GL1`` and ``SRTM_GL3`` for SRTM 30/90 m.
* ``SRTM_GL1_Ellip`` for ellipsoidal SRTM 30 m.

New tiles are grouped by longitude, for example
``cache_dir/opentopography/AW3D30/E132/ALPSMLC30_N035E132_DSM.tif``.
Existing tiles in the previous catalog-based directory layout are also reused
without moving them. Only missing tiles are downloaded, using the catalog's
original server paths. Product catalogs remain in their product cache directory.

Native WGS84 ellipsoidal variants skip geoid conversion. Orthometric ALOS and
SRTM use EGM96. Unsupported source/resolution combinations raise before any
download; coverage gaps never change the selected source or resolution. Local
directory priority continues to apply before the online source.

These products are OpenTopography's published mirrors, whose versions may
differ from current producer releases. ALOS is a digital surface model and can
include vegetation and buildings. Consult the original dataset descriptions
and attribution requirements:

* `ALOS World 3D <https://portal.opentopography.org/raster?opentopoID=OTALOS.112016.4326.2>`_
* `ALOS Ellipsoidal <https://portal.opentopography.org/raster?opentopoID=OTALOS.082017.4326.1>`_
* `SRTM <https://portal.opentopography.org/raster?opentopoID=OTSRTM.042013.4326.1>`_
* `SRTM Ellipsoidal <https://portal.opentopography.org/raster?opentopoID=OTSRTM.082016.4326.1>`_

Command line
------------

.. code-block:: powershell

    altira download "D:/Images/scene.tif" --cache-dir "D:/DEM"
    altira download "D:/Images/scene.tif" --cache-dir "D:/DEM" --local-path "D:/LocalDEM"
    altira download "D:/Images/scene.tif" --cache-dir "D:/DEM" --source alos-ellipsoidal
    altira download "D:/Images/scene.tif" --cache-dir "D:/DEM" --source srtm --resolution 90

The command prints the available native source raster paths. Repeat
``--local-path`` to supply multiple directories in priority order.
