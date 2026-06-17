"""Road-network intersection generation utilities.

This module creates intersection points from the uploaded road network and then
classifies each point as signalized or non-signalized using OSM traffic-signal
points generated elsewhere in the app.
"""

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, MultiPoint, GeometryCollection


FEET_TO_METERS = 0.3048


def _extract_points(geom):
    """Return point geometries from a Shapely intersection result."""
    if geom is None or geom.is_empty:
        return []

    if geom.geom_type == "Point":
        return [geom]

    if geom.geom_type == "MultiPoint":
        return list(geom.geoms)

    if geom.geom_type == "GeometryCollection":
        pts = []
        for part in geom.geoms:
            pts.extend(_extract_points(part))
        return pts

    # Overlapping lines are intentionally skipped. They usually indicate split
    # road centerlines or coincident features, not a true intersection point.
    return []


def _safe_text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def generate_road_intersections(
    roads,
    signals=None,
    route_col="FULLNAME",
    segment_id_col=None,
    cluster_tolerance_ft=50,
    signal_match_distance_ft=100,
):
    """Generate intersection points from road-line crossings/touching.

    Parameters
    ----------
    roads : geopandas.GeoDataFrame
        Road centerline GeoDataFrame.
    signals : geopandas.GeoDataFrame, optional
        OSM traffic-signal point GeoDataFrame. If provided, intersections within
        signal_match_distance_ft of a signal are classified as Signalized.
    route_col : str
        Road name / route field. Same-name pairs are skipped to avoid creating
        false intersections at internal segment splits.
    segment_id_col : str, optional
        Existing unique road segment ID field, used only for attributes.
    cluster_tolerance_ft : float
        Distance used to merge nearby crossing points into one intersection.
    signal_match_distance_ft : float
        Distance from generated intersection point to OSM signal point for
        classifying the intersection as Signalized.

    Returns
    -------
    geopandas.GeoDataFrame
        Point intersections in EPSG:4326 with fields:
        IntersectionID, IntersectionControl, IsSignalized, RoadName1, RoadName2,
        RoadNames, SignalCnt, SignalIDs, UnitID, UnitType.
    """
    if roads is None or roads.empty:
        return gpd.GeoDataFrame(
            columns=[
                "IntersectionID",
                "IntersectionControl",
                "IsSignalized",
                "RoadName1",
                "RoadName2",
                "RoadNames",
                "SignalCnt",
                "SignalIDs",
                "UnitID",
                "UnitType",
                "geometry",
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )

    roads_proj = roads.copy()
    if roads_proj.crs is None:
        roads_proj = roads_proj.set_crs(4326)
    roads_proj = roads_proj.to_crs(epsg=3857)

    roads_proj = roads_proj[roads_proj.geometry.notna()].copy()
    roads_proj = roads_proj[~roads_proj.geometry.is_empty].copy()
    roads_proj = roads_proj[
        roads_proj.geometry.geom_type.isin(["LineString", "MultiLineString"])
    ].copy()

    if roads_proj.empty:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    roads_proj = roads_proj.explode(index_parts=False).reset_index(drop=True)
    sindex = roads_proj.sindex

    point_rows = []

    for i, row in roads_proj.iterrows():
        geom = row.geometry
        try:
            candidate_idx = list(sindex.query(geom, predicate="intersects"))
        except TypeError:
            candidate_idx = list(sindex.query(geom))

        name_i = _safe_text(row.get(route_col, "")) if route_col in roads_proj.columns else ""
        seg_i = _safe_text(row.get(segment_id_col, "")) if segment_id_col in roads_proj.columns else ""

        for j in candidate_idx:
            if j <= i:
                continue

            other = roads_proj.iloc[j]
            other_geom = other.geometry
            if not geom.intersects(other_geom):
                continue

            name_j = _safe_text(other.get(route_col, "")) if route_col in roads_proj.columns else ""
            seg_j = _safe_text(other.get(segment_id_col, "")) if segment_id_col in roads_proj.columns else ""

            # Avoid false intersections caused by one named route being split
            # into many short centerline pieces.
            if name_i and name_j and name_i.lower() == name_j.lower():
                continue

            inter = geom.intersection(other_geom)
            for pt in _extract_points(inter):
                point_rows.append(
                    {
                        "RoadNameA": name_i,
                        "RoadNameB": name_j,
                        "SegmentIDA": seg_i,
                        "SegmentIDB": seg_j,
                        "geometry": pt,
                    }
                )

    if not point_rows:
        return gpd.GeoDataFrame(
            columns=[
                "IntersectionID",
                "IntersectionControl",
                "IsSignalized",
                "RoadName1",
                "RoadName2",
                "RoadNames",
                "SignalCnt",
                "SignalIDs",
                "UnitID",
                "UnitType",
                "geometry",
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )

    raw_points = gpd.GeoDataFrame(point_rows, geometry="geometry", crs="EPSG:3857")

    tol_m = float(cluster_tolerance_ft) * FEET_TO_METERS
    buffers = raw_points.copy()
    buffers["geometry"] = buffers.geometry.buffer(tol_m)
    dissolved = buffers.dissolve().explode(index_parts=False).reset_index(drop=True)
    clusters = gpd.GeoDataFrame(
        {"ClusterID": range(1, len(dissolved) + 1)},
        geometry=dissolved.geometry,
        crs="EPSG:3857",
    )

    joined = gpd.sjoin(
        raw_points,
        clusters[["ClusterID", "geometry"]],
        how="left",
        predicate="within",
    ).drop(columns=["index_right"], errors="ignore")

    out_rows = []
    for cluster_id, sub in joined.groupby("ClusterID"):
        names = []
        for col in ["RoadNameA", "RoadNameB"]:
            names.extend([_safe_text(v) for v in sub[col].tolist()])
        names = sorted({n for n in names if n})

        geom_union = sub.geometry.unary_union
        centroid = geom_union.centroid

        out_rows.append(
            {
                "IntersectionID": f"INT_{int(cluster_id)}",
                "RoadName1": names[0] if len(names) >= 1 else "",
                "RoadName2": names[1] if len(names) >= 2 else "",
                "RoadNames": " | ".join(names),
                "geometry": centroid,
            }
        )

    intersections = gpd.GeoDataFrame(out_rows, geometry="geometry", crs="EPSG:3857")

    intersections["SignalCnt"] = 0
    intersections["SignalIDs"] = ""
    intersections["IsSignalized"] = False
    intersections["IntersectionControl"] = "Non-signalized"

    if signals is not None and not signals.empty:
        signals_proj = signals.copy()
        if signals_proj.crs is None:
            signals_proj = signals_proj.set_crs(4326)
        signals_proj = signals_proj.to_crs(epsg=3857)
        signals_proj = signals_proj[signals_proj.geometry.notna()].copy()
        signals_proj = signals_proj[~signals_proj.geometry.is_empty].copy()

        if not signals_proj.empty:
            match_m = float(signal_match_distance_ft) * FEET_TO_METERS
            signal_buf = signals_proj.copy()
            signal_buf["SignalJoinID"] = signal_buf.index.astype(str)
            signal_buf["geometry"] = signal_buf.geometry.buffer(match_m)

            hits = gpd.sjoin(
                intersections[["IntersectionID", "geometry"]],
                signal_buf[["SignalJoinID", "geometry"]],
                how="left",
                predicate="within",
            ).drop(columns=["index_right"], errors="ignore")

            if not hits.empty and "SignalJoinID" in hits.columns:
                hit_summary = (
                    hits.dropna(subset=["SignalJoinID"])
                    .groupby("IntersectionID")["SignalJoinID"]
                    .agg(lambda x: sorted(set(map(str, x))))
                    .reset_index()
                )

                signal_lookup = dict(
                    zip(hit_summary["IntersectionID"], hit_summary["SignalJoinID"])
                )

                intersections["SignalIDs"] = intersections["IntersectionID"].map(
                    lambda x: ",".join(signal_lookup.get(x, []))
                )
                intersections["SignalCnt"] = intersections["IntersectionID"].map(
                    lambda x: len(signal_lookup.get(x, []))
                ).fillna(0).astype(int)
                intersections["IsSignalized"] = intersections["SignalCnt"] > 0
                intersections["IntersectionControl"] = intersections["IsSignalized"].map(
                    {True: "Signalized", False: "Non-signalized"}
                )

    intersections["UnitID"] = intersections["IntersectionID"]
    intersections["UnitType"] = "Intersection"

    return intersections.to_crs(epsg=4326).reset_index(drop=True)
