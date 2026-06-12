import geopandas as gpd
import numpy as np


def add_crash_density(
    spatial_units,
    crashes,
    unit_id_col,
    density_type="length",
    crash_id_col=None,
):
    """
    Calculate crash count and crash density for corridors, segments, or intersections.

    density_type:
        "length" = crashes per mile
        "area"   = crashes per square mile
        "count"  = raw crash count
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

    if crash_id_col and crash_id_col in joined.columns:
        counts = (
            joined.groupby(unit_id_col)[crash_id_col]
            .nunique()
            .reset_index(name="CrashCount")
        )
    else:
        counts = (
            joined.groupby(unit_id_col)
            .size()
            .reset_index(name="CrashCount")
        )

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
