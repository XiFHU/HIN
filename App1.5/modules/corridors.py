# modules/corridors.py

import geopandas as gpd


def build_corridors(
    roads,
    signals_with_corridor,
    corridor_width_m=20,
    corridor_search_buffer_m=150,
    min_signals=3,
    city_name="",
    county_name="",
    route_col="FULLNAME"
):
    """
    Build corridor polygons from selected roads and signals.

    This version supports both TIGER roads and custom uploaded roads.

    Method:
    1. Group signals by Route.
    2. Require at least min_signals per corridor.
    3. Match complete roads by selected route_col.
    4. If no full-route match exists, fallback to roads near signals.
    5. Buffer matched roads into corridor polygons.
    """

    if roads is None or signals_with_corridor is None:
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

    if roads.empty or signals_with_corridor.empty:
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

    if route_col not in roads.columns:
        raise ValueError(
            f"{route_col} not found in roads. "
            "Please check selected route name column."
        )

    roads_m = roads.to_crs("EPSG:26913")
    signals_m = signals_with_corridor.to_crs("EPSG:26913")

    corridor_shapes = []

    if "Route" in signals_m.columns:
        groups = signals_m.groupby("Route")
    else:
        signals_m["_all_signals_route"] = "Selected Roads"
        groups = signals_m.groupby("_all_signals_route")

    corridor_id = 1

    for route, group in groups:

        route = str(route).strip()

        if len(group) < min_signals:
            continue

        # First choice:
        # use the complete road with same route name
        matched_roads = roads_m[
            roads_m[route_col]
            .astype(str)
            .str.upper()
            .str.strip()
            == route.upper()
        ].copy()

        if not matched_roads.empty:

            selection_method = "complete route name match"

        else:

            # Fallback:
            # use roads near signals
            corridor_search_area = (
                group.geometry
                .buffer(corridor_search_buffer_m)
                .union_all()
            )

            matched_roads = roads_m[
                roads_m.intersects(corridor_search_area)
            ].copy()

            selection_method = "signal buffer fallback"

        if matched_roads.empty:
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
                "Route": route,
                "City": city_name,
                "County": county_name,
                "SignalCnt": len(group),
                "RoadCnt": len(matched_roads),
                "Method": selection_method,
                "geometry": corridor_poly
            }
        )

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
