import geopandas as gpd
import numpy as np


CRASH_ID_PRIORITY = [
    "DashboardCrashID",
    "SourceCrashID",
    "CrashID",
    "CRASH_ID",
    "Crash_ID",
    "crash_id",
    "CaseID",
    "CASE_ID",
    "Case_ID",
    "ST_CASE",
    "OBJECTID",
]


def resolve_crash_id_col(df, crash_id_col=None):
    """Return the best crash ID column available for unique crash counting."""

    if df is None:
        return None

    if crash_id_col and crash_id_col in df.columns:
        return crash_id_col

    for col in CRASH_ID_PRIORITY:
        if col in df.columns:
            return col

    normalized = {
        str(c).lower().replace(" ", "").replace("_", ""): c
        for c in df.columns
    }

    for key in [
        "dashboardcrashid",
        "sourcecrashid",
        "crashid",
        "caseid",
        "stcase",
        "objectid",
        "accidentid",
    ]:
        if key in normalized:
            return normalized[key]

    return None


def _count_unique_crashes(joined, unit_id_col, crash_id_col=None):
    """Count unique crashes by spatial unit, falling back to row count only when no crash ID exists."""

    if joined is None or joined.empty:
        return None

    id_col = resolve_crash_id_col(joined, crash_id_col)

    if id_col is not None:
        work = joined[[unit_id_col, id_col]].copy()
        work[id_col] = work[id_col].fillna("").astype(str).str.strip()
        work = work[work[id_col] != ""]

        if not work.empty:
            return (
                work.groupby(unit_id_col)[id_col]
                .nunique()
                .reset_index(name="CrashCount")
            )

    return (
        joined.groupby(unit_id_col)
        .size()
        .reset_index(name="CrashCount")
    )


def add_crash_density(
    spatial_units,
    crashes,
    unit_id_col,
    density_type="length",
    crash_id_col=None,
):
    """
    Calculate unique crash count and crash density for corridors, segments, or intersections.

    CrashCount is the count of unique crash records. It should use the mapped
    crash ID from the crash field mapping step when available. If no mapped or
    canonical crash ID exists, the function falls back to row count.

    density_type:
        "length" = unique crashes per mile
        "area"   = unique crashes per square mile
        "count"  = raw unique crash count
    """

    if spatial_units is None or spatial_units.empty:
        return spatial_units

    spatial_units = spatial_units.copy()

    if crashes is None or crashes.empty:
        spatial_units["CrashCount"] = 0
        spatial_units["CrashDensity"] = 0
        return spatial_units

    if spatial_units.crs != crashes.crs:
        crashes = crashes.to_crs(spatial_units.crs)

    join_cols = [unit_id_col, "geometry"]

    joined = gpd.sjoin(
        crashes,
        spatial_units[join_cols],
        how="inner",
        predicate="intersects"
    )

    counts = _count_unique_crashes(
        joined,
        unit_id_col,
        crash_id_col=crash_id_col,
    )

    if counts is None:
        spatial_units["CrashCount"] = 0
    else:
        spatial_units = spatial_units.merge(
            counts,
            on=unit_id_col,
            how="left"
        )
        spatial_units["CrashCount"] = spatial_units["CrashCount"].fillna(0)

    if density_type == "length":
        spatial_units["Length_Miles"] = spatial_units.geometry.length / 5280
        spatial_units["CrashDensity"] = np.where(
            spatial_units["Length_Miles"] > 0,
            spatial_units["CrashCount"] / spatial_units["Length_Miles"],
            0
        )

    elif density_type == "area":
        spatial_units["Area_SqMi"] = spatial_units.geometry.area / 27878400
        spatial_units["CrashDensity"] = np.where(
            spatial_units["Area_SqMi"] > 0,
            spatial_units["CrashCount"] / spatial_units["Area_SqMi"],
            0
        )

    else:
        spatial_units["CrashDensity"] = spatial_units["CrashCount"]

    return spatial_units
