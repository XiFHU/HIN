# modules/signals.py

import geopandas as gpd
import osmnx as ox
import numpy as np

from shapely.geometry import Point
from sklearn.cluster import DBSCAN


PROJECTED_CRS = "EPSG:26913"


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
    Join each signal to nearby named TIGER roads and create CorridorID.

    Important:
    One SignalID can appear multiple times if the signal belongs to
    multiple corridors at an intersection.
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

    roads_m = roads.to_crs(PROJECTED_CRS)
    signals_m = signals.to_crs(PROJECTED_CRS).copy()

    if "SignalID" not in signals_m.columns:
        signals_m["SignalID"] = (
            signals_m.index + 1
        )

    if "City" not in signals_m.columns:
        signals_m["City"] = city_name

    if "County" not in signals_m.columns:
        signals_m["County"] = county_name

    road_cols = [
        road_name_col,
        "geometry"
    ]

    if road_type_col in roads_m.columns:
        road_cols.append(
            road_type_col
        )

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

    signals_with_road = gpd.sjoin_nearest(
        signals_m,
        roads_named[road_cols],
        how="left",
        distance_col="DistRoad",
        max_distance=max_distance_m
    )

    signals_with_road = signals_with_road[
        signals_with_road[road_name_col].notna()
    ].copy()

    signals_with_road = signals_with_road.rename(
        columns={
            road_name_col: "Route",
            road_type_col: "RoadType"
        }
    )

    signals_with_road["City"] = (
        signals_with_road["City"]
        .fillna(city_name)
    )

    signals_with_road["County"] = (
        signals_with_road["County"]
        .fillna(county_name)
    )

    signals_with_road["Corridor_Key"] = (
        signals_with_road["Route"]
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

    signals_final = signals_with_road[
        signals_with_road["Corridor_Key"].isin(
            valid_corridors
        )
    ].copy()

    corridor_id_map = {
        key: i + 1
        for i, key in enumerate(
            sorted(
                signals_final[
                    "Corridor_Key"
                ].unique()
            )
        )
    }

    signals_final["CorridorID"] = (
        signals_final["Corridor_Key"]
        .map(corridor_id_map)
    )

    signals_final = signals_final.drop(
        columns=[
            "index_right"
        ],
        errors="ignore"
    )

    return signals_final.to_crs("EPSG:4326")


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

    return (
        signals
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
