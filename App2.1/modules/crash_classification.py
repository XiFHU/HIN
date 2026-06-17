# modules/crash_classification.py

import geopandas as gpd
import pandas as pd
from shapely.ops import substring


PROJECTED_CRS = "EPSG:26913"

def derive_kabco_from_count_columns(
    df,
    k_col=None,
    a_col=None,
    b_col=None,
    c_col=None,
    o_col=None
):
    df = df.copy()

    severity_columns = [
        ("K", k_col),
        ("A", a_col),
        ("B", b_col),
        ("C", c_col),
        ("O", o_col),
    ]

    def classify_row(row):

        for severity, col in severity_columns:

            if col is None:
                continue

            if col not in row.index:
                continue

            value = pd.to_numeric(
                row[col],
                errors="coerce"
            )

            if pd.notna(value) and value > 0:
                return severity

        return "O"

    df["KABCO"] = df.apply(
        classify_row,
        axis=1
    )

    return df


def create_intersection_units(
    signals,
    buffer_ft=250
):
    """
    Create intersection spatial units from signal points.
    """

    if signals is None or signals.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    signals_m = signals.to_crs(PROJECTED_CRS).copy()

    id_col = (
        "SignalID"
        if "SignalID" in signals_m.columns
        else None
    )

    units = gpd.GeoDataFrame(
        signals_m.drop(columns="geometry"),
        geometry=signals_m.geometry.buffer(
            buffer_ft * 0.3048
        ),
        crs=PROJECTED_CRS
    )

    if id_col:
        units["IntersectionID"] = (
            signals_m[id_col].values
        )
    else:
        units["IntersectionID"] = (
            units.index + 1
        )

    units["UnitID"] = (
        "INT_"
        + units["IntersectionID"].astype(str)
    )

    units["UnitType"] = "Intersection"

    return units.to_crs("EPSG:4326")


def create_corridor_units(
    corridors
):
    """
    Prepare corridor spatial units.
    """

    if corridors is None or corridors.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    units = corridors.copy()

    if "CorridorID" in units.columns:
        units["UnitID"] = (
            "COR_"
            + units["CorridorID"].astype(str)
        )
    elif "corridor_id" in units.columns:
        units["UnitID"] = (
            "COR_"
            + units["corridor_id"].astype(str)
        )
    else:
        units["UnitID"] = (
            "COR_"
            + (units.index + 1).astype(str)
        )

    units["UnitType"] = "Corridor"

    return units.to_crs("EPSG:4326")


def split_line_by_length(
    line,
    segment_length_m
):
    """
    Split a LineString into equal-length pieces.
    """

    if line.length <= segment_length_m:
        return [line]

    segments = []

    start = 0.0

    while start < line.length:
        end = min(
            start + segment_length_m,
            line.length
        )

        seg = substring(
            line,
            start,
            end
        )

        if not seg.is_empty:
            segments.append(seg)

        start = end

    return segments


def create_road_segment_units(
    roads,
    segment_length_ft=500
):
    """
    Split selected roads into fixed-length segment units.
    """

    if roads is None or roads.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    roads_m = roads.to_crs(PROJECTED_CRS).copy()

    roads_m = roads_m[
        roads_m.geometry.geom_type.isin(
            ["LineString", "MultiLineString"]
        )
    ].copy()

    segment_length_m = segment_length_ft * 0.3048

    segment_rows = []

    segment_id = 1

    for _, row in roads_m.iterrows():

        geom = row.geometry

        if geom.geom_type == "MultiLineString":
            parts = list(geom.geoms)
        else:
            parts = [geom]

        for part in parts:

            pieces = split_line_by_length(
                part,
                segment_length_m
            )

            for piece in pieces:

                new_row = row.copy()
                new_row.geometry = piece
                new_row["SegmentID"] = segment_id
                new_row["UnitID"] = f"SEG_{segment_id}"
                new_row["UnitType"] = "Segment"
                new_row["Segment_Length_Ft"] = (
                    piece.length / 0.3048
                )

                segment_rows.append(new_row)

                segment_id += 1

    if not segment_rows:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    segments = gpd.GeoDataFrame(
        segment_rows,
        geometry="geometry",
        crs=PROJECTED_CRS
    )

    return segments.to_crs("EPSG:4326")


def assign_crashes_to_units(
    crashes,
    units,
    unit_id_col="UnitID",
    method="within",
    search_distance_ft=100
):
    """
    Assign crashes to spatial units.

    For polygon units:
    - use within

    For line segment units:
    - use nearest with max distance
    """

    if crashes is None or crashes.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    if units is None or units.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    crashes_m = crashes.to_crs(PROJECTED_CRS).copy()
    units_m = units.to_crs(PROJECTED_CRS).copy()

    if method == "nearest":

        assigned = gpd.sjoin_nearest(
            crashes_m,
            units_m[
                [
                    unit_id_col,
                    "UnitType",
                    "geometry"
                ]
            ],
            how="inner",
            max_distance=search_distance_ft * 0.3048,
            distance_col="DistToUnit_M"
        )

    else:

        assigned = gpd.sjoin(
            crashes_m,
            units_m[
                [
                    unit_id_col,
                    "UnitType",
                    "geometry"
                ]
            ],
            how="inner",
            predicate="within"
        )

    assigned = assigned.drop(
        columns=["index_right"],
        errors="ignore"
    )

    return assigned.to_crs("EPSG:4326")


def summarize_kabco(
    assigned_crashes,
    unit_id_col="UnitID"
):
    """
    Summarize KABCO by spatial unit.
    """

    if assigned_crashes is None or assigned_crashes.empty:
        return pd.DataFrame()

    possible_kabco_cols = [
        "KABCO",
        "kabco",
        "Severity",
        "severity",
        "CRASH_SEVERITY",
        "Crash Severity",
        "INJURY_SEVERITY",
        "injury_severity"
    ]

    kabco_col = None

    for c in assigned_crashes.columns:
        if c in possible_kabco_cols:
            kabco_col = c
            break

    if kabco_col is None:
        summary = (
            assigned_crashes
            .groupby(unit_id_col)
            .size()
            .reset_index(name="Total")
        )

        return summary

    summary = (
        assigned_crashes
        .groupby([unit_id_col, kabco_col])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )

    numeric_cols = [
        c for c in summary.columns
        if c != unit_id_col
    ]

    summary["Total"] = (
        summary[numeric_cols]
        .sum(axis=1)
    )

    return summary
