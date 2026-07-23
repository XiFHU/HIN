import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import LineString, MultiLineString


METERS_PER_MILE = 1609.344


def _explode_lines(gdf):
    gdf = gdf.copy()
    gdf = gdf[gdf.geometry.notna()]
    gdf = gdf[gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    return gdf


def _get_route_axis(group):
    bounds = group.total_bounds
    xmin, ymin, xmax, ymax = bounds

    dx = xmax - xmin
    dy = ymax - ymin

    if dx >= dy:
        return "EW"
    else:
        return "NS"


def _sort_segments_by_geometry(group, direction_method="Auto Detect"):
    group = group.copy()

    if direction_method == "Auto Detect":
        axis = _get_route_axis(group)
    elif direction_method == "East-West":
        axis = "EW"
    elif direction_method == "North-South":
        axis = "NS"
    else:
        axis = _get_route_axis(group)

    group["_centroid_x"] = group.geometry.centroid.x
    group["_centroid_y"] = group.geometry.centroid.y

    if axis == "EW":
        group["_route_sort"] = group["_centroid_x"]
    else:
        group["_route_sort"] = group["_centroid_y"]

    group = group.sort_values("_route_sort").reset_index(drop=True)

    return group, axis


def _linear_unit_to_meters(crs):
    """Return the CRS linear-unit conversion factor to meters."""
    try:
        factor = float(crs.axis_info[0].unit_conversion_factor)
        if factor > 0:
            return factor
    except (AttributeError, IndexError, TypeError, ValueError):
        pass

    return 1.0


def generate_from_to_mile(
    roads,
    route_col,
    segment_id_col,
    direction_method="Auto Detect",
    start_mile=0.0,
):
    roads = roads.copy()

    if roads.crs is None:
        raise ValueError("Uploaded road layer has no CRS. Please define CRS before upload.")

    missing_columns = [
        column_name
        for column_name in (route_col, segment_id_col)
        if column_name not in roads.columns
    ]
    if missing_columns:
        raise ValueError(
            "Road layer is missing required column(s): "
            + ", ".join(missing_columns)
        )

    roads = _explode_lines(roads)
    if roads.empty:
        raise ValueError(
            "Uploaded road layer does not contain any LineString or MultiLineString geometry."
        )

    if roads.crs.is_geographic:
        projected_crs = roads.estimate_utm_crs()
        if projected_crs is None:
            projected_crs = "EPSG:3857"
        roads = roads.to_crs(projected_crs)

    linear_unit_to_meters = _linear_unit_to_meters(roads.crs)

    output_parts = []

    for route_name, group in roads.groupby(route_col, dropna=False):
        group = group.copy()

        group, axis = _sort_segments_by_geometry(
            group,
            direction_method=direction_method
        )

        current_mile = float(start_mile)

        from_miles = []
        to_miles = []
        seg_lengths = []
        route_orders = []

        for order_num, (_, row) in enumerate(group.iterrows(), start=1):
            seg_len_mile = (
                row.geometry.length
                * linear_unit_to_meters
                / METERS_PER_MILE
            )

            from_mile = current_mile
            to_mile = current_mile + seg_len_mile

            from_miles.append(from_mile)
            to_miles.append(to_mile)
            seg_lengths.append(seg_len_mile)
            route_orders.append(order_num)

            current_mile = to_mile

        group["RouteName_Calc"] = route_name
        group["RouteOrder_Calc"] = route_orders
        group["RouteAxis_Calc"] = axis
        group["FromMile"] = from_miles
        group["ToMile"] = to_miles
        group["SegmentLength_Mile"] = seg_lengths

        output_parts.append(group)

    if not output_parts:
        raise ValueError("No road routes were available for milepost generation.")

    out = pd.concat(output_parts, ignore_index=True)
    out = gpd.GeoDataFrame(out, geometry="geometry", crs=roads.crs)

    drop_cols = ["_centroid_x", "_centroid_y", "_route_sort"]
    out = out.drop(columns=[c for c in drop_cols if c in out.columns])

    return out
