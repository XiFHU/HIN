# modules/corridors.py

import geopandas as gpd
import pandas as pd


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


def _empty_corridors():
    return gpd.GeoDataFrame(
        columns=[
            "CorridorID",
            "Route",
            "Route_Normalized",
            "City",
            "County",
            "SignalCnt",
            "RoadCnt",
            "Method",
            "RoadClassFilterCol",
            "RoadClassFilterValues",
            "geometry"
        ],
        geometry="geometry",
        crs="EPSG:4326"
    )


def assign_signal_route_from_roads(
    signals,
    roads,
    route_col="FULLNAME",
    search_distance_m=75
):
    """
    Assign route names to signals using nearest uploaded road file.

    This should use the full/base road layer so signal route names remain stable.
    """

    if signals is None or roads is None:
        return signals

    if signals.empty or roads.empty:
        return signals

    if route_col not in roads.columns:
        raise ValueError(
            f"{route_col} not found in roads. "
            "Please check selected route name column."
        )

    signals_m = signals.to_crs(PROJECTED_CRS).copy()
    roads_m = roads.to_crs(PROJECTED_CRS).copy()

    roads_m = roads_m[
        roads_m[route_col].notna()
    ].copy()

    roads_m = roads_m[
        roads_m.geometry.geom_type.isin(
            ["LineString", "MultiLineString"]
        )
    ].copy()

    if roads_m.empty:
        signals_m["Route"] = None
        signals_m["Route_Normalized"] = None
        signals_m["MatchedRoadName"] = None
        signals_m["RoadMatchDistM"] = None

        return signals_m.to_crs("EPSG:4326")

    joined = gpd.sjoin_nearest(
        signals_m,
        roads_m[
            [
                route_col,
                "geometry"
            ]
        ],
        how="left",
        max_distance=search_distance_m,
        distance_col="RoadMatchDistM"
    )

    joined["Route"] = (
        joined[route_col]
        .astype(str)
        .str.strip()
    )

    joined["Route_Normalized"] = (
        joined["Route"]
        .apply(normalize_road_name)
    )

    joined["MatchedRoadName"] = joined["Route"]

    joined = joined.drop(
        columns=[
            "index_right"
        ],
        errors="ignore"
    )

    return joined.to_crs("EPSG:4326")


def _filter_roads_by_class(
    roads,
    road_class_col=None,
    selected_road_classes=None
):
    """
    Filter roads used to create corridor geometry.

    If road_class_col or selected_road_classes is not provided, all roads are kept.
    """

    if roads is None or roads.empty:
        return roads

    if (
        road_class_col is None
        or road_class_col == ""
        or selected_road_classes is None
        or len(selected_road_classes) == 0
    ):
        return roads.copy()

    if road_class_col not in roads.columns:
        raise ValueError(
            f"{road_class_col} not found in roads. "
            "Please check selected road class column."
        )

    selected_values = [
        str(v)
        for v in selected_road_classes
    ]

    filtered = roads[
        roads[road_class_col]
        .astype(str)
        .isin(selected_values)
    ].copy()

    return filtered


def build_corridors(
    roads,
    signals_with_corridor,
    corridor_width_m=20,
    corridor_search_buffer_m=150,
    signal_route_search_distance_m=75,
    min_signals=3,
    city_name="",
    county_name="",
    route_col="FULLNAME",
    use_uploaded_road_names_for_signals=True,
    road_class_col=None,
    selected_road_classes=None,
    export_debug_csv=False,
    debug_csv_path="Corridor_Build_Debug.csv"
):
    """
    Build corridor polygons from roads and signals.

    Important logic:
    1. Signal route assignment can use the full/base road layer.
    2. Corridor geometry can use a filtered road-class layer.
    3. This allows signals to keep stable route names while excluding
       Local/Private roads from final corridor polygons.
    """

    if roads is None or signals_with_corridor is None:
        return _empty_corridors()

    if roads.empty or signals_with_corridor.empty:
        return _empty_corridors()

    if route_col not in roads.columns:
        raise ValueError(
            f"{route_col} not found in roads. "
            "Please check selected route name column."
        )

    roads_full = roads.copy()
    signals_with_corridor = signals_with_corridor.copy()

    if use_uploaded_road_names_for_signals:
        signals_with_corridor = assign_signal_route_from_roads(
            signals=signals_with_corridor,
            roads=roads_full,
            route_col=route_col,
            search_distance_m=signal_route_search_distance_m
        )

    roads_for_geometry = _filter_roads_by_class(
        roads=roads_full,
        road_class_col=road_class_col,
        selected_road_classes=selected_road_classes
    )

    if roads_for_geometry is None or roads_for_geometry.empty:
        return _empty_corridors()

    roads_m = roads_for_geometry.to_crs(PROJECTED_CRS).copy()
    signals_m = signals_with_corridor.to_crs(PROJECTED_CRS).copy()

    roads_m = roads_m[
        roads_m[route_col].notna()
    ].copy()

    roads_m = roads_m[
        roads_m.geometry.geom_type.isin(
            ["LineString", "MultiLineString"]
        )
    ].copy()

    if roads_m.empty:
        return _empty_corridors()

    roads_m["_route_clean"] = (
        roads_m[route_col]
        .apply(normalize_road_name)
    )

    corridor_shapes = []
    debug_rows = []

    if "Route" in signals_m.columns:

        signals_m["Route"] = (
            signals_m["Route"]
            .astype(str)
            .str.strip()
        )

        if "Route_Normalized" not in signals_m.columns:
            signals_m["Route_Normalized"] = (
                signals_m["Route"]
                .apply(normalize_road_name)
            )
        else:
            signals_m["Route_Normalized"] = (
                signals_m["Route_Normalized"]
                .apply(normalize_road_name)
            )

        signals_m = signals_m[
            signals_m["Route_Normalized"].notna()
            & (signals_m["Route_Normalized"] != "")
            & (signals_m["Route_Normalized"].str.upper() != "NONE")
            & (signals_m["Route_Normalized"].str.upper() != "NAN")
        ].copy()

        groups = signals_m.groupby("Route_Normalized")

    else:

        signals_m["_all_signals_route"] = "Selected Roads"
        signals_m["Route"] = "Selected Roads"
        signals_m["Route_Normalized"] = "SELECTED ROADS"

        groups = signals_m.groupby("_all_signals_route")

    corridor_id = 1

    road_class_values_text = ""

    if selected_road_classes is not None:
        road_class_values_text = ", ".join(
            [
                str(v)
                for v in selected_road_classes
            ]
        )

    for route_key, group in groups:

        route_normalized = normalize_road_name(route_key)

        route_display = (
            group["Route"]
            .dropna()
            .astype(str)
            .iloc[0]
            if "Route" in group.columns and not group["Route"].dropna().empty
            else str(route_key)
        )

        exact_match_roads = roads_m[
            roads_m["_route_clean"] == route_normalized
        ].copy()

        exact_match_count = len(exact_match_roads)

        if len(group) < min_signals:

            debug_rows.append(
                {
                    "Route": route_display,
                    "Route_Normalized": route_normalized,
                    "SignalCnt": len(group),
                    "ExactMatchRoadCnt": exact_match_count,
                    "RoadCnt": 0,
                    "Method": "FAILED - less than min_signals"
                }
            )

            continue

        if not exact_match_roads.empty:

            matched_roads = exact_match_roads.copy()
            selection_method = "complete normalized road name match"

        else:

            corridor_search_area = (
                group.geometry
                .buffer(corridor_search_buffer_m)
                .union_all()
            )

            matched_roads = roads_m[
                roads_m.intersects(corridor_search_area)
            ].copy()

            selection_method = "signal buffer fallback filtered roads"

        if matched_roads.empty:

            debug_rows.append(
                {
                    "Route": route_display,
                    "Route_Normalized": route_normalized,
                    "SignalCnt": len(group),
                    "ExactMatchRoadCnt": exact_match_count,
                    "RoadCnt": 0,
                    "Method": "FAILED - no filtered roads found"
                }
            )

            continue

        matched_roads["geom_wkt"] = (
            matched_roads.geometry.to_wkt()
        )

        matched_roads = (
            matched_roads
            .drop_duplicates(subset=["geom_wkt"])
            .drop(columns=["geom_wkt"])
        )

        road_union = matched_roads.geometry.union_all()

        corridor_poly = road_union.buffer(
            corridor_width_m / 2,
            cap_style=2,
            join_style=2
        )

        corridor_shapes.append(
            {
                "CorridorID": corridor_id,
                "Route": route_display,
                "Route_Normalized": route_normalized,
                "City": city_name,
                "County": county_name,
                "SignalCnt": len(group),
                "RoadCnt": len(matched_roads),
                "Method": selection_method,
                "RoadClassFilterCol": road_class_col,
                "RoadClassFilterValues": road_class_values_text,
                "geometry": corridor_poly
            }
        )

        debug_rows.append(
            {
                "Route": route_display,
                "Route_Normalized": route_normalized,
                "SignalCnt": len(group),
                "ExactMatchRoadCnt": exact_match_count,
                "RoadCnt": len(matched_roads),
                "Method": selection_method
            }
        )

        corridor_id += 1

    debug_df = pd.DataFrame(debug_rows)

    if not debug_df.empty:
        print("\n=== Corridor Build Summary ===")
        print(
            debug_df
            .sort_values(
                [
                    "SignalCnt",
                    "RoadCnt"
                ],
                ascending=False
            )
        )

        if export_debug_csv:
            debug_df.to_csv(
                debug_csv_path,
                index=False
            )

    if not corridor_shapes:
        return _empty_corridors()

    corridors = gpd.GeoDataFrame(
        corridor_shapes,
        crs=PROJECTED_CRS
    )

    return corridors.to_crs("EPSG:4326")
