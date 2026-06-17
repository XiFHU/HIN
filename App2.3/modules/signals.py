# modules/signals.py

import geopandas as gpd
import osmnx as ox
import numpy as np

from shapely.geometry import Point
from sklearn.cluster import DBSCAN


PROJECTED_CRS = "EPSG:26913"


def normalize_road_name(name):
    if name is None:
        return ""

    name = str(name).upper().strip()

    replacements = {
        " NORTH ": " N ",
        " SOUTH ": " S ",
        " EAST ": " E ",
        " WEST ": " W ",
        " N. ": " N ",
        " S. ": " S ",
        " E. ": " E ",
        " W. ": " W ",
        " STREET": " ST",
        " ROAD": " RD",
        " AVENUE": " AVE",
        " BOULEVARD": " BLVD",
        " DRIVE": " DR",
        " LANE": " LN",
        " COURT": " CT",
        " PLACE": " PL",
        " PARKWAY": " PKWY",
        " HIGHWAY": " HWY"
    }

    name = " " + name + " "

    for old, new in replacements.items():
        name = name.replace(old, new)

    name = " ".join(name.split())

    return name


def download_signals(boundary_gdf):
    """
    Download OSM traffic signals inside selected boundary.
    """

    polygon = boundary_gdf.geometry.union_all()

    tags = {
        "highway": "traffic_signals"
    }

    signals = ox.features_from_polygon(
        polygon,
        tags
    )

    signals = signals[
        signals.geometry.type == "Point"
    ].copy()

    signals = signals.reset_index(drop=True)

    if signals.crs is None:
        signals = signals.set_crs("EPSG:4326")

    return signals.to_crs("EPSG:4326")


def remove_duplicate_signals(
    signals,
    distance_m=45
):
    """
    Remove duplicate OSM signals using DBSCAN.

    One cluster becomes one averaged point.
    """

    if signals is None or signals.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    signals_m = signals.to_crs(PROJECTED_CRS)

    coords = np.column_stack([
        signals_m.geometry.x,
        signals_m.geometry.y
    ])

    db = DBSCAN(
        eps=distance_m,
        min_samples=1
    ).fit(coords)

    signals_m["cluster_id"] = db.labels_

    def average_cluster(group):
        rep = group.iloc[0].copy()

        rep.geometry = Point(
            group.geometry.x.mean(),
            group.geometry.y.mean()
        )

        return rep

    signals_clean = (
        signals_m
        .groupby(
            "cluster_id",
            group_keys=False
        )
        .apply(average_cluster)
        .reset_index(drop=True)
    )

    signals_clean = signals_clean.drop(
        columns=["cluster_id"],
        errors="ignore"
    )

    signals_clean = gpd.GeoDataFrame(
        signals_clean,
        geometry="geometry",
        crs=PROJECTED_CRS
    )

    return signals_clean.to_crs("EPSG:4326")


def filter_signals_to_roads(
    signals,
    roads,
    max_distance_ft=150
):
    """
    Keep only signals near selected roads.
    """

    if signals is None or signals.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    if roads is None or roads.empty:
        return signals

    roads_m = roads.to_crs(PROJECTED_CRS)
    signals_m = signals.to_crs(PROJECTED_CRS)

    road_lines = roads_m[
        roads_m.geometry.geom_type.isin(
            ["LineString", "MultiLineString"]
        )
    ].copy()

    if road_lines.empty:
        return signals

    road_union = road_lines.geometry.union_all()

    max_distance_m = max_distance_ft * 0.3048

    signals_m["dist_to_selected_roads"] = (
        signals_m.geometry.distance(
            road_union
        )
    )

    signals_m = signals_m[
        signals_m["dist_to_selected_roads"] <= max_distance_m
    ].copy()

    signals_m = signals_m.drop(
        columns=["dist_to_selected_roads"],
        errors="ignore"
    )

    return signals_m.to_crs("EPSG:4326")


def assign_corridor_ids_to_signals(
    signals,
    roads,
    city_name="",
    county_name="",
    min_signals=3,
    max_distance_m=50,
    road_name_col="FULLNAME",
    road_type_col="MTFCC"
):
    """
    Join each signal to nearby named roads and create CorridorID.

    Corridor assignment is multi-route by design:
    - one intersection signal may be assigned to both crossing streets;
    - one signal counts once for each different route;
    - duplicate rows caused by split road segments are removed for the same
      SignalID + Route_Normalized pair.

    Signals on routes with at least min_signals receive CorridorID. Signals
    not on valid corridors remain in the table, but CorridorID is null.
    """

    if signals is None or signals.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    if roads is None or roads.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    if road_name_col not in roads.columns:
        raise ValueError(
            f"{road_name_col} not found in roads."
        )

    roads_m = roads.to_crs(PROJECTED_CRS).copy()
    signals_m = signals.to_crs(PROJECTED_CRS).copy()

    if "SignalID" not in signals_m.columns:
        signals_m["SignalID"] = (
            signals_m.index + 1
        )

    if "City" not in signals_m.columns:
        signals_m["City"] = city_name

    if "County" not in signals_m.columns:
        signals_m["County"] = county_name

    roads_named = roads_m[
        roads_m[road_name_col].notna()
    ].copy()

    roads_named = roads_named[
        roads_named.geometry.geom_type.isin(
            ["LineString", "MultiLineString"]
        )
    ].copy()

    if roads_named.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    roads_named["__matched_road_geometry"] = (
        roads_named.geometry
    )

    road_cols = [
        road_name_col,
        "__matched_road_geometry",
        "geometry"
    ]

    if (
        road_type_col in roads_named.columns
        and road_type_col not in road_cols
    ):
        road_cols.append(
            road_type_col
        )

    signals_buffer = signals_m.copy()
    signals_buffer["__signal_geometry"] = (
        signals_m.geometry
    )

    signals_buffer["geometry"] = (
        signals_buffer.geometry.buffer(
            max_distance_m
        )
    )

    signals_with_road = gpd.sjoin(
        signals_buffer,
        roads_named[road_cols],
        how="inner",
        predicate="intersects"
    )

    if signals_with_road.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    signals_with_road = signals_with_road[
        signals_with_road[
            road_name_col
        ].notna()
    ].copy()

    if signals_with_road.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    signals_with_road["geometry"] = (
        signals_with_road["__signal_geometry"]
    )

    signals_with_road = gpd.GeoDataFrame(
        signals_with_road,
        geometry="geometry",
        crs=PROJECTED_CRS
    )

    signals_with_road["DistRoad"] = (
        signals_with_road.apply(
            lambda row: row.geometry.distance(
                row["__matched_road_geometry"]
            ),
            axis=1
        )
    )

    rename_cols = {
        road_name_col: "Route"
    }

    if road_type_col in signals_with_road.columns:
        rename_cols[road_type_col] = "RoadType"

    signals_with_road = signals_with_road.rename(
        columns=rename_cols
    )

    signals_with_road["Route"] = (
        signals_with_road["Route"]
        .astype(str)
        .str.strip()
    )

    signals_with_road["Route_Normalized"] = (
        signals_with_road["Route"]
        .apply(normalize_road_name)
    )

    signals_with_road = signals_with_road[
        signals_with_road["Route_Normalized"].notna()
        & (signals_with_road["Route_Normalized"] != "")
        & (signals_with_road["Route_Normalized"].str.upper() != "NONE")
        & (signals_with_road["Route_Normalized"].str.upper() != "NAN")
    ].copy()

    if signals_with_road.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    signals_with_road["City"] = (
        signals_with_road["City"]
        .fillna(city_name)
    )

    signals_with_road.loc[
        signals_with_road["City"]
        .astype(str)
        .str.strip()
        == "",
        "City"
    ] = city_name

    signals_with_road["County"] = (
        signals_with_road["County"]
        .fillna(county_name)
    )

    signals_with_road.loc[
        signals_with_road["County"]
        .astype(str)
        .str.strip()
        == "",
        "County"
    ] = county_name

    # Keep one row for each physical signal on each different street.
    # This preserves normal intersection logic while preventing one split road
    # from inflating the corridor signal count.
    signals_with_road = (
        signals_with_road
        .sort_values(
            [
                "SignalID",
                "Route_Normalized",
                "DistRoad"
            ]
        )
        .drop_duplicates(
            subset=[
                "SignalID",
                "Route_Normalized"
            ],
            keep="first"
        )
        .copy()
    )

    signals_with_road["Corridor_Key"] = (
        signals_with_road["Route_Normalized"]
        .astype(str)
        .str.strip()
        + "|"
        + signals_with_road["City"]
        .astype(str)
        .str.strip()
        + "|"
        + signals_with_road["County"]
        .astype(str)
        .str.strip()
    )

    corridor_counts = (
        signals_with_road[
            ["Corridor_Key", "SignalID"]
        ]
        .drop_duplicates()
        ["Corridor_Key"]
        .value_counts()
    )

    valid_corridors = corridor_counts[
        corridor_counts >= min_signals
    ].index

    signals_with_road["IsValidCorridorSignal"] = (
        signals_with_road["Corridor_Key"].isin(
            valid_corridors
        )
    )

    valid_signal_rows = signals_with_road[
        signals_with_road["IsValidCorridorSignal"]
    ].copy()

    corridor_id_map = {
        key: i + 1
        for i, key in enumerate(
            sorted(
                valid_signal_rows[
                    "Corridor_Key"
                ].unique()
            )
        )
    }

    signals_with_road["CorridorID"] = (
        signals_with_road["Corridor_Key"]
        .map(corridor_id_map)
    )

    signals_with_road = signals_with_road.drop(
        columns=[
            "index_right",
            "__signal_geometry",
            "__matched_road_geometry"
        ],
        errors="ignore"
    )

    return signals_with_road.to_crs("EPSG:4326")

def corridor_signal_summary(signals):
    """
    One row per CorridorID / Route.
    Counts unique SignalID values.
    """

    if (
        signals is None
        or signals.empty
        or "CorridorID" not in signals.columns
    ):
        return None

    valid_signals = signals[
        signals["CorridorID"].notna()
    ].copy()

    if valid_signals.empty:
        return None

    return (
        valid_signals
        .groupby(
            ["CorridorID", "Route"]
        )
        .agg(
            Signal_Count=(
                "SignalID",
                "nunique"
            )
        )
        .reset_index()
        .sort_values(
            "CorridorID"
        )
    )


def create_intersection_buffers(
    signals,
    buffer_ft=250
):
    """
    Create intersection buffers from signals.
    """

    if signals is None or signals.empty:
        return gpd.GeoDataFrame(
            geometry=[],
            crs="EPSG:4326"
        )

    signals_m = signals.to_crs(
        PROJECTED_CRS
    )

    buffers = gpd.GeoDataFrame(
        geometry=signals_m.buffer(
            buffer_ft * 0.3048
        ),
        crs=PROJECTED_CRS
    )

    if "SignalID" in signals_m.columns:
        buffers["SignalID"] = (
            signals_m["SignalID"].values
        )

    buffers["intersection_id"] = (
        buffers.index + 1
    )

    return buffers.to_crs("EPSG:4326")
