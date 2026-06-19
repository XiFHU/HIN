import io
import numpy as np
import pandas as pd
import geopandas as gpd
import folium

from shapely.ops import substring, linemerge, unary_union

def section7_clean_risk_segments(
    risk_segments,
    route_col
):

    keep_cols = [
        "SegID",
        route_col,
        "FromMile",
        "ToMile",
        "Crash_Count",
        "EPDO",
        "Max_Window_Score",
        "HIN_Priority_Index",
        "Risk_Score",
        "Risk_Flag",
        "Risk_Class"
    ]

    return clean_section7_output_gdf(
        risk_segments,
        keep_cols
    )


def section7_clean_risk_corridors(
    risk_corridors,
    route_col
):

    keep_cols = [
        "CorridorID",
        route_col,
        "FromMile",
        "ToMile",
        "Segment_Count",
        "Max_HIN_Index",
        "Avg_HIN_Index"
    ]

    return clean_section7_output_gdf(
        risk_corridors,
        keep_cols
    )


def clean_section7_output_gdf(
    gdf,
    keep_cols
):

    if gdf is None:
        return gdf

    gdf_clean = gdf.copy()

    final_cols = [
        c for c in keep_cols
        if c in gdf_clean.columns
    ]

    if "geometry" in gdf_clean.columns:
        final_cols.append("geometry")

    gdf_clean = gdf_clean[
        final_cols
    ].copy()

    for col in gdf_clean.columns:

        if col == "geometry":
            continue

        gdf_clean[col] = (
            gdf_clean[col]
            .apply(
                lambda x:
                None
                if pd.isna(x)
                else str(x)
            )
        )

    return gdf_clean


def estimate_projected_crs(gdf):
    try:
        return gdf.estimate_utm_crs()
    except Exception:
        return "EPSG:3857"


def clean_linestring(geom):
    if geom is None or geom.is_empty:
        return None

    if geom.geom_type == "LineString":
        return geom

    if geom.geom_type == "MultiLineString":
        try:
            merged = linemerge(geom)

            if merged.geom_type == "LineString":
                return merged

            return max(
                list(merged.geoms),
                key=lambda g: g.length
            )

        except Exception:
            return max(
                list(geom.geoms),
                key=lambda g: g.length
            )

    return None


def segment_line(line, segment_len_m):
    rows = []

    total_len = line.length
    start_m = 0.0
    seg_id = 1

    while start_m < total_len:
        end_m = min(
            start_m + segment_len_m,
            total_len
        )

        if end_m > start_m:
            geom = substring(
                line,
                start_m,
                end_m
            )

            rows.append(
                {
                    "SegID": seg_id,
                    "Seg_Start_M": start_m,
                    "Seg_End_M": end_m,
                    "Seg_Length_M": end_m - start_m,
                    "Seg_Length_Mi": (end_m - start_m) / 1609.344,
                    "geometry": geom
                }
            )

        start_m = end_m
        seg_id += 1

    return rows


def create_equal_length_segments(
    roads_proj,
    route_col,
    segment_length_mi
):
    segment_len_m = segment_length_mi * 1609.344

    all_rows = []

    for route_name, grp in roads_proj.groupby(route_col):
        merged_geom = unary_union(
            grp.geometry
        )

        line = clean_linestring(
            merged_geom
        )

        if line is None:
            continue

        seg_rows = segment_line(
            line,
            segment_len_m
        )

        for r in seg_rows:
            r[route_col] = route_name

        all_rows.extend(
            seg_rows
        )

    if len(all_rows) == 0:
        return gpd.GeoDataFrame(
            columns=[
                route_col,
                "SegID",
                "Seg_Start_M",
                "Seg_End_M",
                "Seg_Length_M",
                "Seg_Length_Mi",
                "geometry"
            ],
            geometry="geometry",
            crs=roads_proj.crs
        )

    return gpd.GeoDataFrame(
        all_rows,
        geometry="geometry",
        crs=roads_proj.crs
    )


def prepare_uploaded_segments(
    roads_proj,
    route_col,
    segment_id_col=None
):
    segs = roads_proj.copy()

    if (
        segment_id_col is not None
        and
        segment_id_col in segs.columns
    ):
        segs["SegID"] = (
            segs[segment_id_col]
            .astype(str)
        )

    elif "SegmentID" in segs.columns:
        segs["SegID"] = (
            segs["SegmentID"]
            .astype(str)
        )

    else:
        segs["SegID"] = range(
            1,
            len(segs) + 1
        )

    segs["Seg_Length_M"] = (
        segs.geometry.length
    )

    segs["Seg_Length_Mi"] = (
        segs["Seg_Length_M"] / 1609.344
    )

    segs["Seg_Start_M"] = np.nan
    segs["Seg_End_M"] = np.nan

    return segs


def create_route_lines(
    base_segments,
    route_col
):
    route_rows = []

    for route_name, grp in base_segments.groupby(route_col):
        merged_geom = unary_union(
            grp.geometry
        )

        line = clean_linestring(
            merged_geom
        )

        if line is None:
            continue

        route_rows.append(
            {
                route_col: route_name,
                "Route_Length_M": line.length,
                "Route_Length_Mi": line.length / 1609.344,
                "geometry": line
            }
        )

    return gpd.GeoDataFrame(
        route_rows,
        geometry="geometry",
        crs=base_segments.crs
    )


def assign_crashes_to_routes(
    crashes_proj,
    route_lines,
    route_col,
    max_dist_m
):
    crashes_work = crashes_proj.copy()

    crashes_work["CrashID_S7"] = range(
        1,
        len(crashes_work) + 1
    )

    joined = gpd.sjoin_nearest(
        crashes_work,
        route_lines[
            [
                route_col,
                "geometry"
            ]
        ],
        how="left",
        max_distance=max_dist_m,
        distance_col="Route_Dist_M"
    )

    joined = joined.dropna(
        subset=[
            route_col
        ]
    ).copy()

    if joined.empty:
        return joined

    route_geom_dict = dict(
        zip(
            route_lines[route_col],
            route_lines.geometry
        )
    )

    joined["Route_Pos_M"] = joined.apply(
        lambda r: route_geom_dict[
            r[route_col]
        ].project(
            r.geometry
        ),
        axis=1
    )

    return joined


def apply_epdo(
    crashes_df,
    kabco_col,
    epdo_weights
):
    crashes_df = crashes_df.copy()

    crashes_df["KABCO_Clean"] = (
        crashes_df[kabco_col]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    crashes_df["EPDO"] = (
        crashes_df["KABCO_Clean"]
        .map(epdo_weights)
        .fillna(0)
    )

    return crashes_df


def create_sliding_windows(
    route_lines,
    crashes_route,
    route_col,
    window_len_mi,
    step_len_mi,
    risk_metric
):
    window_len_m = window_len_mi * 1609.344
    step_len_m = step_len_mi * 1609.344

    window_rows = []

    for _, route in route_lines.iterrows():
        route_name = route[route_col]
        line = route.geometry
        route_len_m = line.length

        route_crashes = crashes_route[
            crashes_route[route_col] == route_name
        ].copy()

        start_m = 0.0
        win_id = 1

        while start_m + window_len_m <= route_len_m + 1e-9:
            end_m = start_m + window_len_m

            c = route_crashes[
                (
                    route_crashes["Route_Pos_M"] >= start_m
                )
                &
                (
                    route_crashes["Route_Pos_M"] < end_m
                )
            ].copy()

            crash_count = len(c)

            epdo_total = (
                c["EPDO"].sum()
                if "EPDO" in c.columns
                else crash_count
            )

            length_mi = (
                end_m - start_m
            ) / 1609.344

            if risk_metric == "Crash Count":
                score = crash_count

            elif risk_metric == "Crash Density":
                score = (
                    crash_count / length_mi
                    if length_mi > 0
                    else 0
                )

            elif risk_metric == "EPDO":
                score = epdo_total

            elif risk_metric == "EPDO Density":
                score = (
                    epdo_total / length_mi
                    if length_mi > 0
                    else 0
                )

            else:
                score = crash_count

            geom = substring(
                line,
                start_m,
                end_m
            )

            window_rows.append(
                {
                    route_col: route_name,
                    "WindowID": win_id,
                    "Win_Start_M": start_m,
                    "Win_End_M": end_m,
                    "Win_From_Mi": start_m / 1609.344,
                    "Win_To_Mi": end_m / 1609.344,
                    "Window_Length_Mi": length_mi,
                    "Crash_Count": crash_count,
                    "EPDO": epdo_total,
                    "Window_Score": score,
                    "geometry": geom
                }
            )

            start_m += step_len_m
            win_id += 1

    return gpd.GeoDataFrame(
        window_rows,
        geometry="geometry",
        crs=route_lines.crs
    )


def score_segments(
    base_segments,
    risk_windows,
    route_col,
    top_percent
):
    segs = base_segments.copy()

    positive_windows = risk_windows[
        risk_windows["Window_Score"] > 0
    ].copy()

    if positive_windows.empty:
        segs["Crash_Count"] = 0
        segs["EPDO"] = 0
        segs["Max_Window_Score"] = 0
        segs["HIN_Priority_Index"] = 0
        segs["Risk_Score"] = 0
        segs["Risk_Flag"] = False
        segs["Risk_Class"] = "Not Risky"

        return segs, positive_windows, 0

    raw_window_threshold = positive_windows[
        "Window_Score"
    ].quantile(
        1 - top_percent / 100
    )

    risky_windows = positive_windows[
        positive_windows["Window_Score"] >= raw_window_threshold
    ].copy()

    max_scores = []
    max_crash_counts = []
    max_epdo_scores = []

    for _, seg in segs.iterrows():
        route_name = seg[route_col]

        touching = risk_windows[
            risk_windows[route_col] == route_name
        ]

        touching = touching[
            touching.geometry.intersects(
                seg.geometry
            )
        ]

        if touching.empty:
            max_scores.append(0)
            max_crash_counts.append(0)
            max_epdo_scores.append(0)

        else:
            max_score = touching[
                "Window_Score"
            ].max()

            max_crash_count = (
                touching["Crash_Count"].max()
                if "Crash_Count" in touching.columns
                else 0
            )

            max_epdo = (
                touching["EPDO"].max()
                if "EPDO" in touching.columns
                else max_crash_count
            )

            max_scores.append(
                max_score
            )

            max_crash_counts.append(
                max_crash_count
            )

            max_epdo_scores.append(
                max_epdo
            )

    segs["Max_Window_Score"] = max_scores
    segs["Crash_Count"] = max_crash_counts
    segs["EPDO"] = max_epdo_scores

    max_raw_score = float(
        pd.to_numeric(
            segs["Max_Window_Score"],
            errors="coerce"
        ).max()
    )

    if pd.isna(max_raw_score) or max_raw_score <= 0:
        segs["HIN_Priority_Index"] = 0
    else:
        segs["HIN_Priority_Index"] = (
            pd.to_numeric(
                segs["Max_Window_Score"],
                errors="coerce"
            ).fillna(0) / max_raw_score * 100
        )

    # Backward-compatible alias. Use HIN_Priority_Index in the UI/map.
    segs["Risk_Score"] = segs["HIN_Priority_Index"]

    positive_segments = segs[
        segs["HIN_Priority_Index"] > 0
    ].copy()

    if positive_segments.empty:
        threshold = 0
        segs["Risk_Flag"] = False
    else:
        threshold = positive_segments["HIN_Priority_Index"].quantile(
            1 - top_percent / 100
        )
        segs["Risk_Flag"] = (
            segs["HIN_Priority_Index"] >= threshold
        )

    segs["Risk_Class"] = np.where(
        segs["Risk_Flag"],
        "Risky",
        "Not Risky"
    )

    return segs, risky_windows, threshold

def build_risk_corridors(
    risk_segments,
    route_col
):
    risky = risk_segments[
        risk_segments["Risk_Flag"] == True
    ].copy()

    corridor_rows = []

    if risky.empty:
        return gpd.GeoDataFrame(
            columns=[
                route_col,
                "CorridorID",
                "Segment_Count",
                "Max_HIN_Index",
                "Avg_HIN_Index",
                "geometry"
            ],
            geometry="geometry",
            crs=risk_segments.crs
        )

    for route_name, grp in risky.groupby(route_col):
        dissolved = grp.dissolve(
            by=route_col,
            as_index=False
        )

        geom = dissolved.geometry.iloc[0]

        if geom.geom_type == "MultiLineString":
            geoms = list(
                geom.geoms
            )
        else:
            geoms = [
                geom
            ]

        for i, g in enumerate(
            geoms,
            start=1
        ):
            related = grp[
                grp.geometry.intersects(g)
            ]

            corridor_rows.append(
                {
                    route_col: route_name,
                    "CorridorID": f"{route_name}_{i}",
                    "Segment_Count": len(related),
                    "Max_HIN_Index": related["HIN_Priority_Index"].max(),
                    "Avg_HIN_Index": related["HIN_Priority_Index"].mean(),
                    "geometry": g
                }
            )

    return gpd.GeoDataFrame(
        corridor_rows,
        geometry="geometry",
        crs=risk_segments.crs
    )


def run_sliding_window_risk_analysis(
    roads,
    crashes,
    route_col,
    segmentation_method,
    segment_length_mi,
    window_len_mi,
    step_len_mi,
    top_percent,
    crash_snap_dist_ft,
    risk_metric,
    kabco_col=None,
    epdo_weights=None,
    segment_id_col=None,
    min_crash_count=None
):
    roads_work = roads.copy()
    crashes_work = crashes.copy()

    if roads_work.crs is None:
        roads_work = roads_work.set_crs(
            epsg=4326
        )

    if crashes_work.crs is None:
        crashes_work = crashes_work.set_crs(
            epsg=4326
        )

    projected_crs = estimate_projected_crs(
        roads_work
    )

    roads_proj = roads_work.to_crs(
        projected_crs
    )

    crashes_proj = crashes_work.to_crs(
        projected_crs
    )

    if segmentation_method in [
        "Use equal-length segments",
        "Use window-increment segments"
    ]:
        base_segments = create_equal_length_segments(
            roads_proj,
            route_col,
            segment_length_mi
        )

    else:
        base_segments = prepare_uploaded_segments(
            roads_proj,
            route_col,
            segment_id_col
        )

    if base_segments.empty:
        raise ValueError(
            "No base segments were created."
        )

    route_lines = create_route_lines(
        base_segments,
        route_col
    )

    if route_lines.empty:
        raise ValueError(
            "No route lines were created."
        )

    crash_snap_dist_m = (
        crash_snap_dist_ft * 0.3048
    )

    crashes_route = assign_crashes_to_routes(
        crashes_proj,
        route_lines,
        route_col,
        crash_snap_dist_m
    )

    if risk_metric in [
        "EPDO",
        "EPDO Density"
    ]:
        if kabco_col is None:
            raise ValueError(
                "KABCO column is required for EPDO analysis."
            )

        if epdo_weights is None:
            epdo_weights = {
                "K": 12,
                "A": 5,
                "B": 3,
                "C": 2,
                "O": 1
            }

        crashes_route = apply_epdo(
            crashes_route,
            kabco_col,
            epdo_weights
        )

    risk_windows = create_sliding_windows(
        route_lines,
        crashes_route,
        route_col,
        window_len_mi,
        step_len_mi,
        risk_metric
    )

    if risk_windows.empty:
        raise ValueError(
            "No sliding windows were created. Try reducing the window length."
        )

    risk_segments, risky_windows, risk_threshold = score_segments(
        base_segments,
        risk_windows,
        route_col,
        top_percent
    )

    if min_crash_count is not None and min_crash_count > 0:
        risk_segments = risk_segments[
            risk_segments["Crash_Count"] >= min_crash_count
        ].copy()

        positive_segments = risk_segments[
            risk_segments["HIN_Priority_Index"] > 0
        ].copy()

        if positive_segments.empty:
            risk_threshold = 0
            risk_segments["Risk_Flag"] = False
            risk_segments["Risk_Class"] = "Not Risky"
        else:
            risk_threshold = positive_segments["HIN_Priority_Index"].quantile(
                1 - top_percent / 100
            )
            risk_segments["Risk_Flag"] = (
                risk_segments["HIN_Priority_Index"] >= risk_threshold
            )
            risk_segments["Risk_Class"] = np.where(
                risk_segments["Risk_Flag"],
                "Risky",
                "Not Risky"
            )

    risk_corridors = build_risk_corridors(
        risk_segments,
        route_col
    )

    return {
        "route_lines": route_lines,
        "risk_windows": risk_windows,
        "risky_windows": risky_windows,
        "risk_segments": risk_segments,
        "risk_corridors": risk_corridors,
        "risk_threshold": risk_threshold,
        "assigned_crashes": crashes_route
    }


def color_by_value(value, vmin, vmax):
    if pd.isna(value):
        return "#cccccc"

    if vmax <= vmin:
        return "#d7191c"

    ratio = (
        value - vmin
    ) / (
        vmax - vmin
    )

    if ratio >= 0.75:
        return "#d7191c"

    elif ratio >= 0.50:
        return "#fdae61"

    elif ratio >= 0.25:
        return "#ffffbf"

    else:
        return "#a6d96a"


def get_map_center(gdf):
    if gdf is None or gdf.empty:
        return [
            39.7,
            -104.9
        ]

    gdf_4326 = gdf.to_crs(
        epsg=4326
    ).copy()

    center_geom = (
        gdf_4326
        .geometry
        .union_all()
        .centroid
    )

    return [
        center_geom.y,
        center_geom.x
    ]




def make_section7_context_map(
    route_lines,
    risk_segments,
    route_col
):
    routes = route_lines.to_crs(
        epsg=4326
    ).copy()

    segs = risk_segments.to_crs(
        epsg=4326
    ).copy()

    risky = segs[
        segs["Risk_Flag"] == True
    ].copy()

    center = get_map_center(
        risky if not risky.empty else routes
    )

    m = folium.Map(
        location=center,
        zoom_start=12,
        tiles="CartoDB positron"
    )

    if risky.empty:
        folium.LayerControl(
            collapsed=False
        ).add_to(m)

        return m

    risky_routes = risky[
        route_col
    ].astype(str).unique()

    context_routes = routes[
        routes[route_col]
        .astype(str)
        .isin(risky_routes)
    ].copy()

    corridor_group = folium.FeatureGroup(
        name="Risk Corridors",
        show=True
    )

    for _, row in context_routes.iterrows():
        folium.GeoJson(
            row.geometry,
            style_function=lambda x: {
                "color": "#bdbdbd",
                "weight": 2,
                "opacity": 0.75
            },
            popup=folium.Popup(
                f"""
                Route: {row.get(route_col, "")}<br>
                Corridor Type: Risk Corridor
                """,
                max_width=300
            )
        ).add_to(corridor_group)

    corridor_group.add_to(m)

    vmin = risky["HIN_Priority_Index"].min()
    vmax = risky["HIN_Priority_Index"].max()

    risk_group = folium.FeatureGroup(
        name="Risk Segments",
        show=True
    )

    for _, row in risky.iterrows():
        color = color_by_value(
            row["HIN_Priority_Index"],
            vmin,
            vmax
        )

        folium.GeoJson(
            row.geometry,
            style_function=lambda x, color=color: {
                "color": color,
                "weight": 2,
                "opacity": 1.0
            },
            popup=folium.Popup(
                f"""
                Route: {row.get(route_col, "")}<br>
                Segment ID: {row.get("SegID", "")}<br>
                FromMile: {row.get("FromMile", "")}<br>
                ToMile: {row.get("ToMile", "")}<br>
                HIN Priority Index (0-100): {row.get("HIN_Priority_Index", 0):.3f}<br>
                Risk Class: {row.get("Risk_Class", "")}
                """,
                max_width=300
            )
        ).add_to(risk_group)

    risk_group.add_to(m)

    legend_html = """
    <div style="
        position: fixed;
        bottom: 40px;
        left: 40px;
        width: 190px;
        z-index: 9999;
        background-color: white;
        border: 2px solid black;
        padding: 10px;
        font-size: 13px;
    ">
        <b>HIN Priority Index (0-100)</b><br>
        <i style="background:#a6d96a;width:18px;height:12px;display:inline-block;"></i>
        Low<br>
        <i style="background:#ffffbf;width:18px;height:12px;display:inline-block;"></i>
        Moderate<br>
        <i style="background:#fdae61;width:18px;height:12px;display:inline-block;"></i>
        High<br>
        <i style="background:#d7191c;width:18px;height:12px;display:inline-block;"></i>
        Very High<br>
        <hr style="margin:6px 0;">
        <i style="background:#bdbdbd;width:18px;height:12px;display:inline-block;"></i>
        Risk Corridor
    </div>
    """

    m.get_root().html.add_child(
        folium.Element(
            legend_html
        )
    )

    folium.LayerControl(
        collapsed=False
    ).add_to(m)

    return m



def gdf_to_geojson_bytes(
    gdf
):

    gdf_4326 = gdf.to_crs(
        epsg=4326
    ).copy()

    for col in gdf_4326.columns:

        if col == "geometry":
            continue

        gdf_4326[col] = (
            gdf_4326[col]
            .apply(
                lambda x:
                None
                if pd.isna(x)
                else str(x)
            )
        )

    return (
        gdf_4326
        .to_json()
        .encode("utf-8")
    )

def df_to_csv_bytes(df):
    return (
        df
        .to_csv(index=False)
        .encode("utf-8")
    )


def section7_excel_bytes(
    risk_windows,
    risk_segments,
    risk_corridors
):
    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        risk_windows.drop(
            columns="geometry",
            errors="ignore"
        ).to_excel(
            writer,
            sheet_name="Risk_Windows",
            index=False
        )

        risk_segments.drop(
            columns="geometry",
            errors="ignore"
        ).to_excel(
            writer,
            sheet_name="Risk_Segments",
            index=False
        )

        risk_corridors.drop(
            columns="geometry",
            errors="ignore"
        ).to_excel(
            writer,
            sheet_name="Risk_Corridors",
            index=False
        )

    output.seek(0)

    return output.getvalue()
