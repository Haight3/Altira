
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses calendar versioning in the `YYYY.MM.INC0.PATCH` format.

## [2026.10.2] - (2026-10-11)

### Added

- Added DEM discovery, download, caching, and elevation querying for local datasets and Copernicus, ALOS, and SRTM sources.
- Added a CLI command to preload DEM tiles covering an image or product, with source and resolution selection.
- Added conversion of EGM96 and EGM2008 elevations to WGS84 ellipsoidal heights.

### Changed

- Local DEM directories now take priority over the selected online source, and elevation queries return ellipsoidal heights.
- Documented DEM installation, usage, and online source selection.

### Deprecated

### Removed

### Fixed

- Fix test dependencies for CI

### Security
