# modules/corridors.py

import geopandas as gpd


def build_corridors(
    roads,
    signals,
    corridor_width_m=20,
    corridor_search_buffer_m=150,
    signal_touch_buffer_m=35,
    min_signals=2,
    road_name_col="FULLNAME",
    route_col="Route",
    city_name="",
    county_name=""
):
    """
    Build corridor polygons from TIGER roads and OSM signals.

    Method:
    1. Group signals by Route if Route exists.
    2. Require at least min_signals per corridor.
    3. Search TIGER roads near those signals.
    4. Match TIGER FULLNAME to Route.
    5. Fallback to roads touching signal buffer.
    6. Buffer matched roads into corridor polygons.
    """

    if roads.empty or signals.empty:
        return gpd.GeoDataFrame(
            columns=[
                "CorridorID",
                "Route",
                "City",
                "County",
                "SignalCnt",
                "RoadCnt",
                "Method",
                "geometry"
            ],
            geometry="geometry",
            crs="EPSG:4326"
        )

    if road_name_col not in roads.columns:
        raise ValueError(
            f"{road_name_col} not found in roads. TIGER roads should include FULLNAME."
        )

    roads_m = roads.to_crs("EPSG:26913")
    signals_m = signals.to_crs("EPSG:26913")

    corridor_shapes = []

    if route_col in signals_m.columns:
        groups = signals_m.groupby(route_col)
    else:
        signals_m["_all_signals_route"] = "Selected Roads"
        groups = signals_m.groupby("_all_signals_route")

    corridor_id = 1

    for route, group in groups:
        route = str(route).strip()

        if len(group) < min_signals:
            continue

        corridor_search_area = (
            group.geometry
            .buffer(corridor_search_buffer_m)
            .union_all()
        )

        near_roads = roads_m[
            roads_m.intersects(corridor_search_area)
        ].copy()

        if near_roads.empty:
            continue

        main_roads = near_roads[
            near_roads[road_name_col]
            .astype(str)
            .str.upper()
            .str.strip()
            == route.upper()
        ].copy()

        if not main_roads.empty:
            matched_roads = main_roads.copy()
            selection_method = "route name match"
        else:
            signal_touch_area = (
                group.geometry
                .buffer(signal_touch_buffer_m)
                .union_all()
            )

            matched_roads = near_roads[
                near_roads.intersects(signal_touch_area)
            ].copy()

            selection_method = "signal touch fallback"

        if matched_roads.empty:
            continue

        matched_roads["geom_wkt"] = matched_roads.geometry.to_wkt()

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

        corridor_shapes.append({
            "CorridorID": corridor_id,
            "Route": route,
            "City": city_name,
            "County": county_name,
            "SignalCnt": len(group),
            "RoadCnt": len(matched_roads),
            "Method": selection_method,
            "geometry": corridor_poly
        })

        corridor_id += 1

    if not corridor_shapes:
        return gpd.GeoDataFrame(
            columns=[
                "CorridorID",
                "Route",
                "City",
                "County",
                "SignalCnt",
                "RoadCnt",
                "Method",
                "geometry"
            ],
            geometry="geometry",
            crs="EPSG:4326"
        )

    corridors = gpd.GeoDataFrame(
        corridor_shapes,
        crs="EPSG:26913"
    )

    return corridors.to_crs("EPSG:4326")
