# Satellite CSV generation

This implementation follows the observer location, ENU coordinates, and velocity definitions in the original `8Sat8Gd/starlink_tracker.ipynb` and `oneweb_tracker_no_generation.ipynb`. Local GP caching and provenance records follow `dtc_d2d_ntn_all_constellations`. The reference files are unchanged.

## Files and execution order

| Notebook | Purpose |
|---|---|
| `download_tle.ipynb` | Download all three constellations; archive TLE, OMM JSON, and source manifests by UTC time; fix the shared timeline |
| `starlink_real_tracker.ipynb` | Real Starlink orbits with DTC and low-altitude samples excluded |
| `kuiper_real_tracker.ipynb` | Real Amazon Kuiper / Amazon Leo orbits |
| `oneweb_real_tracker.ipynb` | Real OneWeb orbits |
| `kuiper_approved_missing.ipynb` | Fill estimated population gaps using FCC-approved Gen1 shell parameters |
| `oneweb_approved_missing.ipynb` | Fill estimated population gaps using FCC-approved Phase1 shell parameters |
| `kuiper_custom.ipynb` | Custom synthetic Kuiper orbits and additional satellites |
| `oneweb_custom.ipynb` | Custom synthetic OneWeb orbits and additional satellites |

Run `download_tle.ipynb` first, then the other notebooks as needed. `*_approved_missing.ipynb` requires only the complete catalog from `download_tle.ipynb`; real visible CSVs need not exist first. `*_custom.ipynb` is an independent experiment, not an additional batch for `*_approved_missing.ipynb`. Select one synthetic scenario per constellation when merging.

Use Python 3.10+ and install dependencies in the project directory:

```bash
cd "/home/shizhen/my_project/WorldNTN/generate satellite"
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Select `.venv/bin/python` as the notebook kernel in the IDE. Run tests with `.venv/bin/python -m pytest -q tests`.

## Directory layout

```text
generate satellite/
  download_tle.ipynb / *_real_tracker.ipynb / *_approved_missing.ipynb / *_custom.ipynb
  satellite_pipeline.py         # Downloads, coordinates, real propagation, CSVs, merging
  synthetic_orbits.py           # Two independent synthetic modeling branches
  scenario.json                 # Shared observer, timeline, filters, and input snapshot
  tle/                          # Real inputs; historical snapshots are preserved
    starlink/ kuiper/ oneweb/
    snapshot_<UTC>.json
  orbit_info/                   # Alongside tle/
    approved_shells.csv         # Official parameters with references for each row
    custom_shells.json          # User-defined parameters
    SOURCES.md / sources.json
    official_documents/         # Original FCC PDFs and verification hashes
    generated/                  # Mean elements, phase assumptions, population statistics
  outputs/
    real_gp/<constellation>/<UTC>/
    approved_shell_synthetic/<constellation>/<UTC>/
    custom_synthetic/<constellation>/<UTC>/
```

Downloads, generated orbits, and outputs are ignored by this directory's `.gitignore` but remain on disk. To share a reproducible experiment, include `scenario.json`, the corresponding `tle` snapshot, `orbit_info/generated`, and output metadata. Filename timestamps identify download/generation times; orbital epochs are recorded separately.

## Downloads and completeness

The [CelesTrak GP format documentation](https://celestrak.org/NORAD/documentation/gp-data-formats.php) describes the five-digit catalog-number limit of traditional TLEs. `download_tle.ipynb` requests both TLE and complete OMM JSON; propagation prefers JSON and supports six-digit NORAD IDs. Validation checks TLE line lengths, IDs, and checksums, and validates JSON parameters. Records are deduplicated by NORAD ID, retaining the latest epoch. The manifest records URLs, UTC times, SHA256 hashes, counts, epoch ranges, and IDs present in OMM but absent from TLE.

`auto` reuses snapshots from the last two hours, `local` reads offline, and `refresh` requests new data. HTTP error bodies are never saved as TLEs, and failures are recorded per format. Complete propagation input requires successful JSON downloads for all three groups. A TLE failure preserves successful JSON data; eligible five-digit OMM records are converted to `*_derived_from_omm.tle`, with conversion provenance and omitted six-digit IDs recorded separately. This file is a conversion, not a raw TLE download. There are no unlimited retries or silent stale-data fallbacks. Propagation and synthetic-generation notebooks run offline. Skyfield uses its built-in timescale without implicit ephemeris downloads.

## Shared settings and filtering

`scenario.json` defaults to the reference observer `(39.95697°, -105.16033°, 1660 m)`, with samples in `[start, start+24h)` every 120 seconds: 720 timestamps, minimum elevation 25°, all azimuths, and no top-N truncation. The first `download_tle.ipynb` run writes the current UTC start time; subsequent runs preserve it. For a new experiment, edit the time or set `RESET_START_TIME=True` in `download_tle.ipynb`. Constellations must use the same settings for direct merging.

| Constellation | Minimum WGS84 altitude | DTC handling |
|---|---:|---|
| Starlink | 450 km | Original `[DTC]` exclusion plus other explicit DTC name tags |
| Kuiper | 550 km | Exclude explicit DTC tags; do not infer from unverified ID ranges |
| OneWeb | 1100 km | Same as Kuiper |

The Starlink threshold comes from the reference notebook. The other two are adjustable engineering filters, not official operational-status classifications. **Low altitude may indicate orbit raising, deorbiting, or another state; being above the threshold does not guarantee active broadband service.** DTC recognition depends on catalog names and may be incomplete. Add confirmed exclusions through `excluded_norad_ids`. Altitude is filtered at each sample. After changing these rules, regenerate all outputs that will be merged.

Real orbit data defaults to `abs(sample time - element epoch) <= 14 days`, with stale samples recorded individually. Gap generation is refused if the entire catalog used for the estimate is stale. Prefer archived elements near the experiment date; today's TLEs cannot reliably reconstruct distant historical trajectories. See [Skyfield's epoch guidance](https://rhodesmill.org/skyfield/earth-satellites.html#checking-an-element-set-s-epoch).

## CSV fields and coordinates

The first 12 columns preserve the reference format: `Time, Name, Azimuth (°), Elevation (°), Orbit Altitude (km), Slant km, x_East (m), y_North (m), z_Up (m), vx_East (m/s), vy_North (m/s), vz_Up (m/s)`.

Additional fields include one-based `TimeIndex`, globally unique `Satellite ID`, real `NORAD ID`, constellation, source type, synthetic/DTC flags, shell, latitude/longitude, ECEF position/velocity, ECEF/GCRS speed, range rate, element epoch, and input hashes. Synthetic NORAD IDs remain empty; no official IDs or TLEs are fabricated. `Time` uses ISO UTC with `Z` and can be parsed with `pd.to_datetime(..., utc=True)`.

ECEF uses ITRS. ENU is the fixed observer's local east/north/up frame: position is relative to the ground station, and velocity is transformed into the rotating frame before subtracting the station velocity. This includes Earth's rotation and cannot be replaced with a simple rotation of inertial velocity. See the [Skyfield reference-frame API](https://rhodesmill.org/skyfield/api-position.html#skyfield.positionlib.ICRF.frame_xyz_and_velocity).

By default, `*_visible.csv` contains visible samples that meet every threshold, sorted by time and slant range. `write_all_states=true` additionally exports filtered global states in satellite chunks. Each run also writes:

- `counts.csv`: includes timestamps with zero visible satellites; averages use the complete timeline.
- `filter_audit.csv`: per-satellite counts for DTC/manual exclusions, invalid propagation, stale epochs, low altitude, retained samples, and visible samples.
- `metadata.json`: configuration, inputs, propagation method, and completion status. Interrupted or failed runs are marked `failed` and cannot be merged.

## The two synthetic scenarios

`*_approved_missing.ipynb` uses verified approval parameters. Assign the **complete catalog** to shells by inclination (default tolerance ±1°) and mean altitude, accepting altitudes from 200 km to shell altitude +150 km. Satellites raising their orbits and spare satellites count toward existing populations. Generate `max(approved population - assigned catalog population, 0)` satellites per shell, and write `population.csv` and per-satellite `real_assignments.csv`. Excess spares in one shell do not offset a gap at another inclination.

**This is a catalog-based population-gap estimate, not a verified list of unlaunched satellites.** Missing catalog entries, retirements, system assignments, and in-orbit spares affect the estimate. Official documents do not provide future per-satellite RAANs or phases. The implementation constructs reproducible templates within the approved shells: a default RAAN span of 180° for near-polar shells and 360° otherwise, uniform phases within each plane, and Walker F = 1 by default (0 for a single plane). The seed determines the RAAN origin, phases, and gap-template sampling. These are assumptions. Templates are not registered to individual real orbital slots and cannot identify actual vacancies or support collision assessment.

`*_custom.ipynb` depends entirely on `custom_shells.json`, independently of approved parameters. Default counts are examples of additional satellites. Both synthetic branches use circular SGP4 mean orbits with zero drag. Nominal altitude means `a - R_WGS72`, which differs slightly from the position-dependent WGS84 ellipsoidal altitude in CSVs. Initial elements and assumptions are archived for every synthetic satellite; `load_virtual_elements()` supports offline replay.

The last cell of each synthetic notebook provides an explicit merge example. `merge_exports()` checks the shared scenario, input hashes, completion status, and duplicate IDs, and prevents combining both synthetic alternatives for the same constellation. Merging does not resolve spatial overlap between templates and real orbits.

## Validation scope

`tests/test_pipeline.py` covers rotating-frame velocities against centered position differences, Skyfield ground-geometry comparisons, DTC/altitude/epoch filtering, zero-visibility counts, six-digit IDs, cache completeness, per-shell gaps, reproducible synthetic generation, merge checks, and notebook structure/syntax.

After downloading with `download_tle.ipynb`, run `.venv/bin/python tests/smoke_notebooks.py` for a smoke test. It copies inputs to a temporary directory and executes all eight notebooks offline, propagating only two timestamps and at most eight satellites per constellation. Approved population-gap accounting still uses the complete catalog. It does not change the production `scenario.json` or run a full 24-hour simulation.
