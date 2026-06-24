"""Step 7 sliding window risk analysis UI."""

from ..map_symbology import (
    add_categorical_legend,
    categorical_color_lookup,
    crash_marker_style,
    make_numeric_colormap,
    render_crash_color_controls,
    render_numeric_symbology_controls,
)


def _build_original_crash_density_layer(selected_roads, crashes_s7, segment_id_col, crash_snap_dist_ft):
    """Build crash density on the original uploaded/selected road segments."""

    if selected_roads is None or crashes_s7 is None:
        return None

    original_units = selected_roads.copy()

    if original_units.empty or crashes_s7.empty:
        return original_units

    if segment_id_col is not None and segment_id_col in original_units.columns:
        original_units["UnitID"] = original_units[segment_id_col].astype(str)
    else:
        original_units["UnitID"] = [f"ROAD_{i + 1}" for i in range(len(original_units))]

    original_units["UnitType"] = "Original Road Segment"

    assigned_original = assign_crashes_to_units(
        crashes_s7,
        original_units,
        unit_id_col="UnitID",
        method="nearest",
        search_distance_ft=crash_snap_dist_ft
    )

    crash_counts = (
        assigned_original
        .groupby("UnitID")
        .size()
        .reset_index(name="CrashCount")
    )

    original_density = original_units.merge(
        crash_counts,
        on="UnitID",
        how="left"
    )

    original_density["CrashCount"] = (
        original_density["CrashCount"]
        .fillna(0)
        .astype(int)
    )

    original_density_proj = original_density.to_crs(epsg=3857)
    original_density["Length_Miles"] = original_density_proj.geometry.length / 1609.344
    original_density["CrashDensity"] = np.where(
        original_density["Length_Miles"] > 0,
        original_density["CrashCount"] / original_density["Length_Miles"],
        0
    )

    original_density["CrashDensity"] = (
        original_density["CrashDensity"]
        .replace([np.inf, -np.inf], 0)
        .fillna(0)
    )

    return original_density


def _filter_roads_to_final_corridors(roads, final_corridors):
    """Return only roads that intersect the final, not-dropped corridors."""

    if roads is None:
        return roads

    if final_corridors is None:
        return roads

    if getattr(final_corridors, "empty", True):
        return roads.iloc[0:0].copy()

    if "geometry" not in roads.columns or "geometry" not in final_corridors.columns:
        return roads

    roads_work = roads.copy()
    corridors_work = final_corridors.copy()

    if roads_work.crs is None:
        roads_work = roads_work.set_crs(epsg=4326)

    if corridors_work.crs is None:
        corridors_work = corridors_work.set_crs(roads_work.crs)

    if corridors_work.crs != roads_work.crs:
        corridors_work = corridors_work.to_crs(roads_work.crs)

    valid_roads = (
        roads_work.geometry.notna()
        & ~roads_work.geometry.is_empty
    )

    if not valid_roads.any():
        return roads_work.iloc[0:0].copy()

    try:
        corridor_union = corridors_work.geometry.unary_union
        mask = valid_roads & roads_work.geometry.intersects(corridor_union)
        roads_filtered = roads_work[mask].copy()
    except Exception:
        roads_filtered = roads_work[valid_roads].copy()

    return roads_filtered


def _add_road_class_legend_to_map(fmap, color_lookup):
    """Add a compact road class/type legend for the Segment comparison map.

    The legend is shown only when at least one Roads by Class/Type layer is
    visible. This keeps the map clean when the user has not enabled that
    optional layer.
    """
    if not color_lookup or not st.session_state.get("road_class_legend_enabled", True):
        return fmap

    legend_items = "".join(
        '<div style="white-space:nowrap;"><span style="display:inline-block;width:11px;height:11px;background:'
        + str(color)
        + ';margin-right:5px;border:1px solid #777;"></span>'
        + str(cat)
        + '</div>'
        for cat, color in color_lookup.items()
    )

    legend_html = """
    <div id="road-class-legend" style="
        display: block;
        position: fixed;
        bottom: 45px;
        left: 42px;
        z-index: 9999;
        background: rgba(255, 255, 255, 0.92);
        padding: 7px 9px;
        border: 1px solid #888;
        border-radius: 4px;
        font-size: 11px;
        max-height: 240px;
        max-width: 260px;
        overflow-y: auto;
        box-shadow: 0 1px 4px rgba(0,0,0,0.25);
    ">
        <b>Road Class/Type</b><br>
        {legend_items}
    </div>
    """.replace("{legend_items}", legend_items)
    fmap.get_root().html.add_child(folium.Element(legend_html))

    # Legend visibility is controlled by the optional road-class legend checkbox,
    # not by whether class/type layers are currently toggled on. This keeps the
    # color reference available while comparing layers.

    return fmap


def _ensure_hin_priority_columns(gdf):
    """Add backward-compatible HIN Priority Index fields to old/cached results.

    Older session_state results may still have Risk_Score or Max_Window_Score
    but not HIN_Priority_Index. This helper prevents KeyError after app updates
    or when all rows are filtered out.
    """
    if gdf is None:
        return gdf

    out = gdf.copy()

    if "Max_Window_Score" not in out.columns:
        if "Window_Score" in out.columns:
            out["Max_Window_Score"] = out["Window_Score"]
        elif "Risk_Score" in out.columns:
            out["Max_Window_Score"] = out["Risk_Score"]
        elif "EPDO" in out.columns:
            out["Max_Window_Score"] = out["EPDO"]
        elif "Crash_Count" in out.columns:
            out["Max_Window_Score"] = out["Crash_Count"]
        else:
            out["Max_Window_Score"] = 0

    raw_score = pd.to_numeric(
        out["Max_Window_Score"],
        errors="coerce"
    ).fillna(0)

    if "HIN_Priority_Index" not in out.columns:
        max_raw_score = float(raw_score.max()) if len(raw_score) else 0.0
        if max_raw_score > 0:
            out["HIN_Priority_Index"] = raw_score / max_raw_score * 100
        else:
            out["HIN_Priority_Index"] = 0.0

    out["HIN_Priority_Index"] = pd.to_numeric(
        out["HIN_Priority_Index"],
        errors="coerce"
    ).fillna(0.0)

    if "Risk_Score" not in out.columns:
        out["Risk_Score"] = out["HIN_Priority_Index"]

    if "Crash_Count" not in out.columns:
        out["Crash_Count"] = 0

    if "EPDO" not in out.columns:
        out["EPDO"] = out["Max_Window_Score"]

    if "Risk_Flag" not in out.columns:
        out["Risk_Flag"] = False

    if "Risk_Class" not in out.columns:
        out["Risk_Class"] = np.where(
            out["Risk_Flag"].astype(bool),
            "Risky",
            "Not Risky"
        )

    return out



def _ensure_length_miles_for_hin(gdf):
    if gdf is None or gdf.empty or "Length_Miles" in gdf.columns:
        return gdf
    out = gdf.copy()
    try:
        proj = out.to_crs(epsg=3857)
        out["Length_Miles"] = proj.geometry.length / 1609.344
    except Exception:
        out["Length_Miles"] = 0.0
    return out


def _apply_hin_selection_controls(risk_segments_clean):
    """Compact map-level HIN display selector.

    This controls which HIN segments are displayed on the comparison map. The
    underlying analysis results remain unchanged and can still be downloaded.
    """
    if risk_segments_clean is None or risk_segments_clean.empty:
        return risk_segments_clean, "No HIN segments to display"

    rank_candidates = [
        "HIN_Priority_Index",
        "Max_Window_Score",
        "Crash_Count",
        "EPDO",
        "KSI_Count",
        "Fatal_Injury_Count",
    ]
    rank_options = [c for c in rank_candidates if c in risk_segments_clean.columns]
    if not rank_options:
        rank_options = [risk_segments_clean.columns[0]]

    capture_candidates = [
        "KSI_Count",
        "Fatal_Injury_Count",
        "Crash_Count",
        "EPDO",
        "Max_Window_Score",
    ]
    capture_options = [c for c in capture_candidates if c in risk_segments_clean.columns]

    container = st.popover("HIN selection ▾") if hasattr(st, "popover") else st.expander("HIN selection options", expanded=False)
    with container:
        st.caption(
            "Controls which HIN segments are displayed on this map. "
            "This does not rerun the sliding-window analysis."
        )
        mode = st.selectbox(
            "Select HIN by",
            [
                "All HIN segments",
                "Top X segments",
                "Top X% of segments",
                "Top X% of network miles",
                "Capture at least X% of selected crash metric",
            ],
            key="hin_display_selection_mode",
        )

        rank_by = None
        if mode not in [
            "All HIN segments",
            "Capture at least X% of selected crash metric",
        ]:
            rank_by = st.selectbox(
                "Rank by",
                rank_options,
                index=rank_options.index("HIN_Priority_Index") if "HIN_Priority_Index" in rank_options else 0,
                key="hin_display_rank_by",
            )

        top_n = None
        top_pct = None
        capture_metric = None
        capture_target = None
        manual_threshold = None

        if mode == "Top X segments":
            top_n = st.number_input(
                "Number of top segments",
                min_value=1,
                value=min(50, max(1, len(risk_segments_clean))),
                step=1,
                key="hin_display_top_n",
            )
        elif mode in ["Top X% of segments", "Top X% of network miles"]:
            top_pct = st.number_input(
                "Top percent",
                min_value=0.1,
                max_value=100.0,
                value=10.0,
                step=0.5,
                key="hin_display_top_pct",
            )
        elif mode == "Capture at least X% of selected crash metric":
            if capture_options:
                capture_metric = st.selectbox(
                    "Crash metric to capture",
                    capture_options,
                    index=capture_options.index("Crash_Count") if "Crash_Count" in capture_options else 0,
                    key="hin_display_capture_metric",
                    help=(
                        "The app ranks segments by HIN Priority Index, then adds segments until "
                        "the selected segments capture at least this percent of the selected metric."
                    ),
                )
                capture_target = st.number_input(
                    "Target capture percent",
                    min_value=1.0,
                    max_value=100.0,
                    value=80.0,
                    step=1.0,
                    key="hin_display_capture_pct",
                )
            else:
                st.warning("No crash-count or score columns are available for capture targeting.")

    out = _ensure_hin_priority_columns(risk_segments_clean).copy()
    if mode == "All HIN segments":
        return out, f"Showing all {len(out):,} HIN segments"


    # Most selection methods rank by HIN Priority Index unless the user chooses
    # another field. Capture targeting intentionally ranks by HIN Priority Index
    # and reports the network share required to hit the target.
    if mode == "Capture at least X% of selected crash metric":
        if not capture_metric or capture_metric not in out.columns:
            return out, f"Showing all {len(out):,} HIN segments"
        rank_col = "HIN_Priority_Index" if "HIN_Priority_Index" in out.columns else "Max_Window_Score"
    else:
        rank_col = rank_by if rank_by in out.columns else (
            "HIN_Priority_Index" if "HIN_Priority_Index" in out.columns else "Max_Window_Score"
        )

    out["__rank_value__"] = pd.to_numeric(out[rank_col], errors="coerce").fillna(0)
    ranked = out.sort_values("__rank_value__", ascending=False).copy()

    if mode == "Top X segments":
        n = max(1, int(top_n))
        selected = ranked.head(n).drop(columns=["__rank_value__"], errors="ignore")
        return selected, f"Showing top {len(selected):,} segments by {rank_col}"

    if mode == "Top X% of segments":
        pct = float(top_pct)
        n = max(1, int(round(len(ranked) * pct / 100.0)))
        selected = ranked.head(n).drop(columns=["__rank_value__"], errors="ignore")
        return selected, f"Showing top {pct:g}% of segments by {rank_col} ({len(selected):,} of {len(ranked):,})"

    if mode == "Top X% of network miles":
        ranked = _ensure_length_miles_for_hin(ranked)
        ranked["__length__"] = pd.to_numeric(ranked.get("Length_Miles", 0), errors="coerce").fillna(0)
        total_len = float(ranked["__length__"].sum())
        if total_len <= 0:
            pct = float(top_pct)
            n = max(1, int(round(len(ranked) * pct / 100.0)))
            selected = ranked.head(n).drop(columns=["__rank_value__", "__length__"], errors="ignore")
            return selected, f"Length unavailable; showing top {pct:g}% of segments by {rank_col}"
        target_len = total_len * float(top_pct) / 100.0
        ranked["__cum_length__"] = ranked["__length__"].cumsum()
        selected = ranked[ranked["__cum_length__"] <= target_len].copy()
        if selected.empty:
            selected = ranked.head(1).copy()
        else:
            next_rows = ranked[ranked["__cum_length__"] > target_len].head(1)
            if not next_rows.empty:
                selected = pd.concat([selected, next_rows], ignore_index=False)
        selected_len = float(selected["__length__"].sum())
        selected = selected.drop(columns=["__rank_value__", "__length__", "__cum_length__"], errors="ignore")
        return selected, f"Showing top {float(top_pct):g}% of network miles by {rank_col} ({selected_len:.2f} of {total_len:.2f} mi)"

    if mode == "Capture at least X% of selected crash metric":
        ranked = _ensure_length_miles_for_hin(ranked)
        ranked["__capture__"] = pd.to_numeric(ranked[capture_metric], errors="coerce").fillna(0)
        total_capture = float(ranked["__capture__"].sum())
        if total_capture <= 0:
            selected = ranked.drop(columns=["__rank_value__", "__capture__"], errors="ignore")
            return selected, f"{capture_metric} total is zero; showing all HIN segments"
        target_value = total_capture * float(capture_target) / 100.0
        ranked["__cum_capture__"] = ranked["__capture__"].cumsum()
        selected = ranked[ranked["__cum_capture__"] <= target_value].copy()
        if selected.empty:
            selected = ranked.head(1).copy()
        else:
            next_rows = ranked[ranked["__cum_capture__"] > target_value].head(1)
            if not next_rows.empty:
                selected = pd.concat([selected, next_rows], ignore_index=False)
        selected_capture = float(selected["__capture__"].sum())
        selected_pct = selected_capture / total_capture * 100.0 if total_capture > 0 else 0.0
        selected = _ensure_length_miles_for_hin(selected)
        all_len = pd.to_numeric(ranked.get("Length_Miles", 0), errors="coerce").fillna(0)
        sel_len = pd.to_numeric(selected.get("Length_Miles", 0), errors="coerce").fillna(0)
        total_len = float(all_len.sum()) if len(all_len) else 0.0
        selected_len = float(sel_len.sum()) if len(sel_len) else 0.0
        network_share = selected_len / total_len * 100.0 if total_len > 0 else 0.0
        selected = selected.drop(
            columns=["__rank_value__", "__capture__", "__cum_capture__"],
            errors="ignore",
        )
        return selected, (
            f"Selected {len(selected):,} segments to capture {selected_pct:.1f}% of {capture_metric}; "
            f"network share = {network_share:.1f}% ({selected_len:.2f} of {total_len:.2f} mi)"
        )

    return out.drop(columns=["__rank_value__"], errors="ignore"), f"Showing all {len(out):,} HIN segments"

def _make_segment_comparison_map(
    original_density=None,
    risk_segments=None,
    risk_corridors=None,
    crashes=None,
    roads=None,
    roads_class=None,
    signals=None,
    corridors=None,
    spatial_units=None,
    selected_layers=None,
    crash_density_symbology=None,
    original_density_symbology=None,
    risk_score_symbology=None,
    crash_color_settings=None
):
    """Create the final Segment comparison map with a compact Folium layer control."""

    if selected_layers is None:
        selected_layers = []

    center_source = None

    for gdf in [
        risk_segments,
        original_density,
        risk_corridors,
        spatial_units,
        corridors,
        crashes,
        signals,
        roads
    ]:
        clean_gdf = clean_for_map(gdf)
        if clean_gdf is not None:
            center_source = clean_gdf
            break

    if center_source is not None:
        center_geom = center_source.geometry.union_all().centroid
        location = [center_geom.y, center_geom.x]
        zoom_start = 12
    else:
        location = [39.7, -104.9]
        zoom_start = 10

    fmap = folium.Map(
        location=location,
        zoom_start=zoom_start,
        tiles="CartoDB positron"
    )

    if "Roads" in selected_layers:
        roads = clean_for_map(roads)

        if roads is not None and not roads.empty:
            road_lines = roads[
                roads.geometry.geom_type.isin(["LineString", "MultiLineString"])
            ].copy()

            if not road_lines.empty:
                if "RoadClass" in road_lines.columns:
                    groups = road_lines.groupby("RoadClass")
                else:
                    groups = [("Roads", road_lines)]

                for road_class, sub in groups:
                    folium.GeoJson(
                        make_json_safe_gdf(sub),
                        name=f"Roads - {road_class}",
                        style_function=lambda feature, road_class=road_class: {
                            "color": road_class_color(road_class),
                            "weight": 2,
                            "opacity": 0.65,
                        },
                        tooltip=folium.GeoJsonTooltip(
                            fields=[
                                c for c in [
                                    "FULLNAME",
                                    "RouteName_Calc",
                                    "FromMile",
                                    "ToMile",
                                    "RoadClass",
                                    "RoadType"
                                ]
                                if c in sub.columns
                            ],
                            localize=True
                        ) if any(c in sub.columns for c in ["FULLNAME", "RouteName_Calc", "RoadClass"]) else None
                    ).add_to(fmap)


    if "Roads by Class/Type" in selected_layers:
        roads_class = clean_for_map(roads_class)

        if roads_class is not None and not roads_class.empty:
            road_lines = roads_class[
                roads_class.geometry.geom_type.isin(["LineString", "MultiLineString"])
            ].copy()

            if not road_lines.empty:
                style_col = "RoadStyleClass" if "RoadStyleClass" in road_lines.columns else "RoadClass"
                if style_col in road_lines.columns:
                    categories = sorted(
                        road_lines[style_col]
                        .fillna("Unknown")
                        .astype(str)
                        .unique()
                    )
                    road_lines[style_col] = road_lines[style_col].fillna("Unknown").astype(str)
                    color_lookup = {
                        cat: road_class_color(cat, idx)
                        for idx, cat in enumerate(categories)
                    }
                    groups = [(cat, road_lines[road_lines[style_col] == cat].copy()) for cat in categories]
                else:
                    color_lookup = {"Selected roads": road_class_color("Selected roads", 0)}
                    groups = [("Selected roads", road_lines)]

                for road_class, sub in groups:
                    if sub.empty:
                        continue

                    tooltip_fields = [
                        c for c in [
                            "FULLNAME",
                            "RouteName_Calc",
                            "FromMile",
                            "ToMile",
                            "RoadStyleClass",
                            "RoadClass",
                            "RoadType"
                        ]
                        if c in sub.columns
                    ]

                    color = color_lookup.get(str(road_class), road_class_color(road_class))

                    folium.GeoJson(
                        make_json_safe_gdf(sub),
                        name=f"Roads by Class/Type - {road_class}",
                        show=False,
                        style_function=lambda feature, color=color: {
                            "color": color,
                            "weight": 2,
                            "opacity": 1.0
                        },
                        tooltip=folium.GeoJsonTooltip(
                            fields=tooltip_fields,
                            localize=True
                        ) if tooltip_fields else None
                    ).add_to(fmap)

                fmap = _add_road_class_legend_to_map(fmap, color_lookup)

    if "Signals" in selected_layers:
        signals = clean_for_map(signals)

        if signals is not None and not signals.empty:
            signal_group = folium.FeatureGroup(name="Signals", show=True)

            for _, row in signals.iterrows():
                geom = row.geometry

                if geom.geom_type == "Point":
                    popup_text = ""

                    if "SignalID" in row.index:
                        popup_text += f"SignalID: {row['SignalID']}<br>"

                    if "City" in row.index:
                        popup_text += f"City: {row['City']}<br>"

                    folium.Marker(
                        location=[geom.y, geom.x],
                        icon=folium.DivIcon(html='<div style="font-size:14px;">🚦</div>'),
                        popup=popup_text
                    ).add_to(signal_group)

            signal_group.add_to(fmap)

    if "Corridors" in selected_layers:
        corridors = clean_for_map(corridors)

        if corridors is not None and not corridors.empty:
            tooltip_fields = [
                c for c in [
                    "CorridorID",
                    "Route",
                    "SignalCnt",
                    "CrashCount"
                ]
                if c in corridors.columns
            ]

            folium.GeoJson(
                make_json_safe_gdf(corridors),
                name="Corridors",
                style_function=lambda feature: {
                    "color": "purple",
                    "fillColor": "purple",
                    "weight": 2,
                    "opacity": 0.65,
                    "fillOpacity": 0.08
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    localize=True
                ) if tooltip_fields else None
            ).add_to(fmap)

    if "Current Spatial Units / Crash Density" in selected_layers:
        spatial_units = clean_for_map(spatial_units)

        if spatial_units is not None and not spatial_units.empty:
            spatial_units = make_map_safe_gdf(
                spatial_units,
                numeric_cols=[
                    "CrashDensity",
                    "CrashCount",
                    "Length_Miles",
                    "Area_SqMi"
                ]
            )

            # Ensure this optional layer has a usable crash-density value.
            # Older/previous spatial_units in session_state may only have
            # CrashCount and geometry, which made the map all green. Recompute
            # length-based density here for line units when needed.
            if "Length_Miles" not in spatial_units.columns or pd.to_numeric(
                spatial_units.get("Length_Miles", pd.Series(0, index=spatial_units.index)),
                errors="coerce"
            ).fillna(0).max() <= 0:
                try:
                    spatial_units_proj = spatial_units.to_crs(epsg=3857)
                    spatial_units["Length_Miles"] = spatial_units_proj.geometry.length / 1609.344
                except Exception:
                    spatial_units["Length_Miles"] = 0.0

            if "CrashDensity" not in spatial_units.columns or pd.to_numeric(
                spatial_units.get("CrashDensity", pd.Series(0, index=spatial_units.index)),
                errors="coerce"
            ).fillna(0).max() <= 0:
                if "CrashCount" in spatial_units.columns:
                    crash_count_values = pd.to_numeric(
                        spatial_units["CrashCount"],
                        errors="coerce"
                    ).fillna(0)
                    length_values = pd.to_numeric(
                        spatial_units["Length_Miles"],
                        errors="coerce"
                    ).fillna(0)
                    spatial_units["CrashDensity"] = np.where(
                        length_values > 0,
                        crash_count_values / length_values,
                        0
                    )
                else:
                    spatial_units["CrashDensity"] = 0.0

            values = pd.to_numeric(
                spatial_units["CrashDensity"],
                errors="coerce"
            ).fillna(0)

            spatial_cmap = make_numeric_colormap(
                values,
                cm,
                "Current Spatial Unit Crash Density",
                settings=crash_density_symbology,
            )

            def style_current_spatial_units(feature):
                value = feature["properties"].get("CrashDensity", 0)
                try:
                    value = float(value)
                except Exception:
                    value = 0.0

                color = spatial_cmap(value)

                return {
                    "color": color,
                    "fillColor": color,
                    "weight": 2,
                    "opacity": 0.75,
                    "fillOpacity": 0.35
                }

            tooltip_fields = [
                c for c in [
                    "UnitID",
                    "UnitType",
                    "CrashCount",
                    "CrashDensity",
                    "Length_Miles",
                    "Area_SqMi",
                    "CorridorID",
                    "SegmentID",
                    "Route",
                    "FULLNAME"
                ]
                if c in spatial_units.columns
            ]

            folium.GeoJson(
                make_json_safe_gdf(spatial_units),
                name="Current Spatial Units / Crash Density",
                style_function=style_current_spatial_units,
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    localize=True
                ) if tooltip_fields else None
            ).add_to(fmap)

            spatial_cmap.add_to(fmap)

    if "Original Crash Density" in selected_layers:
        original_density = clean_for_map(original_density)

        if original_density is not None and not original_density.empty:
            original_density = make_map_safe_gdf(
                original_density,
                numeric_cols=[
                    "CrashDensity",
                    "CrashCount",
                    "Length_Miles"
                ]
            )

            values = pd.to_numeric(
                original_density["CrashDensity"],
                errors="coerce"
            ).fillna(0)

            density_cmap = make_numeric_colormap(
                values,
                cm,
                "Original Crash Density",
                settings=original_density_symbology,
            )

            def style_original_density(feature):
                value = feature["properties"].get("CrashDensity", 0)
                try:
                    value = float(value)
                except Exception:
                    value = 0.0

                color = density_cmap(value)

                return {
                    "color": color,
                    "weight": 2,
                    "opacity": 0.8
                }

            tooltip_fields = [
                c for c in [
                    "UnitID",
                    "FULLNAME",
                    "FromMile",
                    "ToMile",
                    "CrashCount",
                    "CrashDensity",
                    "Length_Miles"
                ]
                if c in original_density.columns
            ]

            folium.GeoJson(
                make_json_safe_gdf(original_density),
                name="Original Crash Density",
                style_function=style_original_density,
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    localize=True
                ) if tooltip_fields else None
            ).add_to(fmap)

            density_cmap.add_to(fmap)

    if "Risk Corridors" in selected_layers:
        risk_corridors = clean_for_map(risk_corridors)

        if risk_corridors is not None and not risk_corridors.empty:
            tooltip_fields = [
                c for c in [
                    "CorridorID",
                    "Route",
                    "Max_HIN_Index",
                    "Risk_Segment_Count"
                ]
                if c in risk_corridors.columns
            ]

            folium.GeoJson(
                make_json_safe_gdf(risk_corridors),
                name="Risk Corridors",
                style_function=lambda feature: {
                    "color": "#666666",
                    "weight": 2,
                    "opacity": 0.85,
                    "fillOpacity": 0.0
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    localize=True
                ) if tooltip_fields else None
            ).add_to(fmap)

    if "HIN Priority Index" in selected_layers or "Risk Segments" in selected_layers:
        risk_segments = clean_for_map(risk_segments)

        if risk_segments is not None and not risk_segments.empty:
            risk_segments = make_map_safe_gdf(
                risk_segments,
                numeric_cols=[
                    "HIN_Priority_Index",
                    "CrashCount",
                    "EPDO",
                    "Length_Miles"
                ]
            )

            values = pd.to_numeric(
                risk_segments["HIN_Priority_Index"],
                errors="coerce"
            ).fillna(0)

            risk_cmap = make_numeric_colormap(
                values,
                cm,
                "HIN Priority Index",
                settings=risk_score_symbology,
            )

            def style_risk_segment(feature):
                value = feature["properties"].get("HIN_Priority_Index", 0)
                try:
                    value = float(value)
                except Exception:
                    value = 0.0

                color = risk_cmap(value)

                return {
                    "color": color,
                    "weight": 2,
                    "opacity": 1.0
                }

            tooltip_fields = [
                c for c in [
                    "SegmentID",
                    "UnitID",
                    "Route",
                    "FULLNAME",
                    "HIN_Priority_Index",
                    "CrashCount",
                    "EPDO",
                    "FromMile",
                    "ToMile"
                ]
                if c in risk_segments.columns
            ]

            folium.GeoJson(
                make_json_safe_gdf(risk_segments),
                name="HIN Priority Index",
                style_function=style_risk_segment,
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    localize=True
                ) if tooltip_fields else None
            ).add_to(fmap)

            risk_cmap.add_to(fmap)

    if "Crashes" in selected_layers:
        crashes = clean_for_map(crashes)

        if crashes is not None and not crashes.empty:
            crash_group = folium.FeatureGroup(name="Crashes", show=True)

            crash_color_settings = crash_color_settings or {"enabled": False}
            if crash_color_settings.get("enabled") and crash_color_settings.get("field") in crashes.columns:
                crash_color_settings["color_lookup"] = crash_color_settings.get("color_lookup") or categorical_color_lookup(
                    crashes[crash_color_settings.get("field")].fillna("Unknown")
                )

            for _, row in crashes.iterrows():
                geom = row.geometry

                if geom.geom_type == "Point":
                    popup_text = ""

                    if "SourceCrashID" in row.index:
                        popup_text += f"Case ID: {row['SourceCrashID']}<br>"

                    if "CrashID" in row.index:
                        popup_text += f"App ID: {row['CrashID']}<br>"

                    marker_color, color_value = crash_marker_style(row, crash_color_settings)
                    if color_value is not None:
                        popup_text += f"{crash_color_settings.get('field')}: {color_value}<br>"

                    folium.CircleMarker(
                        location=[geom.y, geom.x],
                        radius=4,
                        color=marker_color,
                        fill_color=marker_color,
                        weight=1.0,
                        fill=True,
                        fill_opacity=0.75,
                        popup=popup_text
                    ).add_to(crash_group)

            crash_group.add_to(fmap)

            if crash_color_settings.get("enabled"):
                fmap = add_categorical_legend(
                    fmap,
                    f"Crashes by {crash_color_settings.get('field')}",
                    crash_color_settings.get("color_lookup"),
                    element_id="section7-crash-color-legend",
                )

    fmap = add_map_elements(fmap)

    fmap.get_root().header.add_child(
        folium.Element(
            """
            <style>
            .leaflet-control-layers {
                font-size: 11px !important;
                max-width: 220px !important;
            }
            .leaflet-control-layers-expanded {
                padding: 4px 6px !important;
            }
            </style>
            """
        )
    )

    folium.LayerControl(
        collapsed=True,
        position="topright"
    ).add_to(fmap)

    return fmap

def render_sliding_window_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    selected_roads = st.session_state.get("selected_roads", None)
    crashes = st.session_state.get("crashes", None)
    final_corridors = st.session_state.get(
        "final_corridors",
        st.session_state.get("corridors", None)
    )

    if selected_roads is None:
        st.warning("Please upload/select roads first.")

    elif crashes is None:
        st.warning("Please upload crash data first.")

    else:
        # V18: run sliding-window analysis on all selected routes, not only the
        # optional corridor context. Corridor layers are used only for map context.
        roads_for_s7 = selected_roads.copy()
        st.caption(
            f"Sliding-window segmentation is using all selected road feature(s): {len(roads_for_s7):,}. "
            "Corridor context, if built, is displayed only as a map layer."
        )

        if roads_for_s7 is None or roads_for_s7.empty:
            st.warning("No selected roads are available for sliding-window segmentation.")
            return

        with st.expander("Analysis Settings", expanded=True):

            route_col_s7 = st.selectbox(
                "Route name column",
                options=list(roads_for_s7.columns),
                index=list(roads_for_s7.columns).index("FULLNAME")
                if "FULLNAME" in roads_for_s7.columns
                else 0,
                key="section7_route_col"
            )

            segment_id_col_s7 = st.session_state.get(
                "segment_id_col",
                None
            )

            segmentation_method = st.selectbox(
                "HIN output segment method",
                [
                    "Use window-increment segments",
                    "Use equal-length segments",
                    "Use existing uploaded road segments"
                ],
                index=0,
                key="section7_segmentation_method",
                help="This controls the final HIN Priority Index line segments shown on the map. It does not change how crashes are counted inside each sliding window."
            )

            with st.expander("How each output segment method works", expanded=False):
                st.markdown(
                    """
                    **Use window-increment segments**  
                    The app splits each route into short segments equal to the window increment. A longer sliding window moves along the route, and each short segment receives the highest overlapping window score. This is the recommended default for sliding-window HIN maps because the displayed segment length is consistent with the step/increment.

                    **Use equal-length segments**  
                    The app splits each route into user-defined equal-length output segments. The sliding window still moves by the increment, but the final displayed HIN segments use the separate segment length entered below. Each equal-length segment receives the highest overlapping window score.

                    **Use existing uploaded road segments**  
                    The app keeps the original uploaded/OSM road segment geometry as the final HIN output unit. Each original segment receives the highest overlapping window score. This is useful when you need results to match an existing GIS roadway layer, but segment lengths may vary and the map may be less comparable across routes.

                    **Score logic for all three methods**  
                    The app first stores the raw maximum overlapping window value as **Max_Window_Score**. If the metric is Crash Count, that raw value is the maximum overlapping window crash count. If the metric is EPDO, that raw value is the maximum overlapping window EPDO total. The displayed **HIN Priority Index** is normalized to a 0–100 scale using: **HIN Priority Index = Max_Window_Score / max(Max_Window_Score) × 100**. This is a relative screening index, not a final adopted HIN designation.
                    """
                )

            col2, col3 = st.columns(2)

            with col2:
                window_len = st.number_input(
                    "Sliding window length (miles)",
                    min_value=0.01,
                    value=0.30,
                    step=0.05,
                    key="section7_window_len",
                    help="Length of the moving analysis window. Crashes inside this distance are counted together for each window position."
                )

            with col3:
                step_len = st.number_input(
                    "Window increment (miles)",
                    min_value=0.01,
                    value=0.10,
                    step=0.05,
                    key="section7_step_len",
                    help="Distance the sliding window moves each step. If you choose window-increment segments, this is also the final map segment length."
                )

            if segmentation_method == "Use equal-length segments":
                segment_length = st.number_input(
                    "Equal output segment length (miles)",
                    min_value=0.01,
                    value=0.10,
                    step=0.05,
                    key="section7_segment_length",
                    help="Final HIN output segment length. Each segment receives the maximum score from any overlapping sliding window."
                )
            elif segmentation_method == "Use window-increment segments":
                segment_length = step_len
            else:
                segment_length = step_len
            top_percent = 100
            crash_snap_dist_ft = st.number_input(
                "Crash-to-route search distance (feet)",
                min_value=10.0,
                value=150.0,
                step=10.0,
                key="section7_crash_snap_dist_ft",
                help="Maximum distance used to snap crashes to the selected route network."
            )

            risk_metric = st.radio(
                "Scoring Metric",
                [
                    "Crash Count",
                    "EPDO"
                ],
                horizontal=True,
                key="section7_risk_metric"
            )

            # Minimum crash filtering is now a Visualization-only display filter.
            # The saved Sliding Window output keeps all generated HIN segments.
            enable_min_crash_filter_s7 = False
            min_crash_count_s7 = 0

            with st.expander("Metric definitions", expanded=False):
                st.markdown(
                    """
                    **How the HIN Priority Index is calculated**

                    1. Crashes are snapped to the nearest selected route within the crash-to-route search distance.
                    2. A fixed-length sliding window moves along each route.
                    3. Each window receives a score.
                    4. Each short output segment receives the highest score from the windows that overlap it.
                    5. The Visualization section lets users display top X, top X%, or top X% of network miles.

                    **Crash Count vs. EPDO**

                    - **Crash Count** counts every crash as 1. A fatal crash, injury crash, and PDO/no-injury crash have the same weight.
                    - **EPDO** is a severity-weighted crash score. Each crash is converted to a weighted value using the K/A/B/C/O weights below, then the weights are summed in each sliding window.
                    - **Max_Window_Score** is the raw maximum score from the windows that overlap each output segment. If the selected metric is Crash Count, this is the maximum overlapping window crash count. If the selected metric is EPDO, this is the maximum overlapping window EPDO total.
                    - **HIN Priority Index** is the normalized 0–100 screening index assigned to each output segment: **HIN Priority Index = Max_Window_Score / max(Max_Window_Score) × 100**. For EPDO analysis, this is equivalent to **Max overlapping window EPDO / max(Max overlapping window EPDO) × 100**. The highest-scoring segment becomes 100, and other segments are scaled relative to it. This index supports HIN screening and comparison; it is not the final adopted HIN designation by itself.
                    Density metrics are not used in the sliding-window selector because fixed-length windows make density and count-based maps nearly identical. Use the Visualization section to compare HIN risk against crash density.
                    """
                )

            section7_crash_source = st.radio(
                "Crash Source",
                [
                    "Use current filtered crashes",
                    "Use all uploaded crashes"
                ],
                horizontal=True,
                key="section7_crash_source"
            )

            if (
                section7_crash_source == "Use current filtered crashes"
                and "filtered_crashes" in st.session_state
            ):
                crashes_s7 = st.session_state["filtered_crashes"].copy()

            elif "all_crashes" in st.session_state:
                crashes_s7 = st.session_state["all_crashes"].copy()

            else:
                crashes_s7 = crashes.copy()

            st.info(
                f"Crash records used: {len(crashes_s7):,}"
            )

            kabco_col = None
            epdo_weights = None

            if risk_metric == "EPDO":

                default_index = (
                    list(crashes_s7.columns).index("KABCO")
                    if "KABCO" in crashes_s7.columns
                    else 0
                )

                kabco_col = st.selectbox(
                    "KABCO / Severity Column",
                    list(crashes_s7.columns),
                    index=default_index,
                    key="section7_kabco_col"
                )

                c1, c2, c3, c4, c5 = st.columns(5)

                with c1:
                    weight_k = st.number_input(
                        "K",
                        min_value=0.0,
                        value=12.0,
                        step=1.0,
                        key="section7_weight_k"
                    )

                with c2:
                    weight_a = st.number_input(
                        "A",
                        min_value=0.0,
                        value=5.0,
                        step=1.0,
                        key="section7_weight_a"
                    )

                with c3:
                    weight_b = st.number_input(
                        "B",
                        min_value=0.0,
                        value=3.0,
                        step=1.0,
                        key="section7_weight_b"
                    )

                with c4:
                    weight_c = st.number_input(
                        "C",
                        min_value=0.0,
                        value=2.0,
                        step=1.0,
                        key="section7_weight_c"
                    )

                with c5:
                    weight_o = st.number_input(
                        "O",
                        min_value=0.0,
                        value=1.0,
                        step=1.0,
                        key="section7_weight_o"
                    )

                epdo_weights = {
                    "K": weight_k,
                    "A": weight_a,
                    "B": weight_b,
                    "C": weight_c,
                    "O": weight_o
                }

        if st.button(
            "Run Sliding Window Risk Analysis",
            type="primary",
            width="stretch",
            key="section7_run_button"
        ):

            results = run_sliding_window_risk_analysis(
                roads=roads_for_s7,
                crashes=crashes_s7,
                route_col=route_col_s7,
                segmentation_method=segmentation_method,
                segment_length_mi=segment_length,
                window_len_mi=window_len,
                step_len_mi=step_len,
                top_percent=top_percent,
                crash_snap_dist_ft=crash_snap_dist_ft,
                risk_metric=risk_metric,
                kabco_col=kabco_col,
                epdo_weights=epdo_weights,
                segment_id_col=segment_id_col_s7,
                min_crash_count=None
            )

            original_density = _build_original_crash_density_layer(
                roads_for_s7,
                crashes_s7,
                segment_id_col_s7,
                crash_snap_dist_ft
            )

            st.session_state["section7_results"] = results
            st.session_state["section7_route_col_s7"] = route_col_s7
            st.session_state["section7_original_density"] = original_density
            st.session_state["section7_crashes_for_map"] = crashes_s7

        if "section7_results" in st.session_state:

            results = st.session_state["section7_results"]
            route_col_s7 = st.session_state["section7_route_col_s7"]

            risk_windows = results["risk_windows"]
            risk_segments = _ensure_hin_priority_columns(
                results["risk_segments"]
            )
            risk_corridors = results["risk_corridors"]
            route_lines = results["route_lines"]


            risk_segments_clean = section7_clean_risk_segments(
                risk_segments,
                route_col_s7
            )

            risk_corridors_clean = section7_clean_risk_corridors(
                risk_corridors,
                route_col_s7
            )

            seg_table = risk_segments_clean.drop(
                columns="geometry",
                errors="ignore"
            )

            if "HIN_Priority_Index" in seg_table.columns:
                seg_table = seg_table.sort_values(
                    "HIN_Priority_Index",
                    ascending=False
                )
            elif "Max_Window_Score" in seg_table.columns:
                seg_table = seg_table.sort_values(
                    "Max_Window_Score",
                    ascending=False
                )
            if "Rank" not in seg_table.columns:
                seg_table.insert(0, "Rank", range(1, len(seg_table) + 1))

            corridor_table = (
                risk_corridors_clean
                .drop(columns="geometry", errors="ignore")
                .sort_values(
                    "Max_HIN_Index",
                    ascending=False
                )
                if not risk_corridors_clean.empty
                else risk_corridors_clean.drop(
                    columns="geometry",
                    errors="ignore"
                )
            )

            dl_col1, dl_col2 = st.columns([0.82, 0.18])
            with dl_col1:
                st.markdown("**HIN risk results**")
            with dl_col2:
                if hasattr(st, "popover"):
                    download_menu = st.popover("☰", use_container_width=False)
                else:
                    download_menu = st.expander("☰", expanded=False)

                with download_menu:
                    st.download_button(
                        "Risk Segments CSV",
                        data=df_to_csv_bytes(
                            seg_table
                        ),
                        file_name="hin_risk_segments.csv",
                        mime="text/csv",
                        key="section7_download_segments_csv"
                    )

                    st.download_button(
                        "Sliding Window Risk Segments GeoJSON",
                        data=gdf_to_geojson_bytes(
                            risk_segments_clean
                        ),
                        file_name="hin_risk_segments.geojson",
                        mime="application/geo+json",
                        key="section7_download_segments_geojson"
                    )

                    st.download_button(
                        "HIN Results Excel",
                        data=section7_excel_bytes(
                            risk_windows,
                            risk_segments_clean,
                            risk_corridors_clean
                        ),
                        file_name="hin_sliding_window_results.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="section7_download_excel"
                    )

                    st.download_button(
                        "HIN Corridors CSV",
                        data=df_to_csv_bytes(
                            corridor_table
                        ),
                        file_name="hin_corridors.csv",
                        mime="text/csv",
                        key="section7_download_corridors_csv"
                    )

            if st.session_state.get("defer_sliding_window_maps", False):
                st.session_state["section7_visualization_ready"] = True
                st.success("HIN results are ready. Open Visualization to display the HIN Priority Index map.")
                return

            # -----------------------------
            # Final Segment Comparison Map
            # -----------------------------

            comparison_layer_options = [
                "HIN Priority Index",
                "Risk Corridors",
                "Original Crash Density",
                "Current Spatial Units / Crash Density",
                "Crashes",
                "Signals",
                "Corridors",
                "Roads",
                "Roads by Class/Type",
            ]

            default_comparison_layers = [
                "HIN Priority Index",
                "Risk Corridors",
                "Original Crash Density",
            ]

            previous_comparison_layers = st.session_state.get(
                "section7_comparison_layers",
                default_comparison_layers
            )
            previous_comparison_layers = [
                layer for layer in previous_comparison_layers
                if layer in comparison_layer_options
            ]

            comparison_layers = st.multiselect(
                "Final comparison map layers",
                comparison_layer_options,
                default=previous_comparison_layers,
                key="section7_comparison_layers",
                help=(
                    "Keeping only the layers you need makes the map much faster. "
                    "Original Crash Density uses the selected road segments as the baseline. "
                    "Current Spatial Units / Crash Density uses the latest Classification / Results spatial units."
                )
            )

            if not comparison_layers:
                st.info(
                    "Select at least one final comparison map layer to draw the Sliding Window map."
                )
                return

            st.caption(
                "Original Crash Density = baseline density on the selected road network. "
                "Current Spatial Units / Crash Density = density from the latest Classification / Results units."
            )

            hin_select_col, _hin_space_col = st.columns([0.34, 0.66])
            with hin_select_col:
                risk_segments_map, hin_selection_summary = _apply_hin_selection_controls(
                    risk_segments_clean
                )
            st.caption(hin_selection_summary)

            risk_corridors_map = risk_corridors_clean
            if (
                risk_segments_map is not None
                and not risk_segments_map.empty
                and risk_corridors_clean is not None
                and not risk_corridors_clean.empty
                and "CorridorID" in risk_segments_map.columns
                and "CorridorID" in risk_corridors_clean.columns
            ):
                selected_corridor_ids = set(risk_segments_map["CorridorID"].astype(str))
                risk_corridors_map = risk_corridors_clean[
                    risk_corridors_clean["CorridorID"].astype(str).isin(selected_corridor_ids)
                ].copy()

            risk_score_symbology = render_numeric_symbology_controls(
                "HIN priority index",
                key_prefix="section7_hin_risk_score",
                default_method="Quantile",
            )

            original_density_symbology = render_numeric_symbology_controls(
                "Original crash density",
                key_prefix="section7_original_crash_density",
                default_method="Capped gradient",
            )

            current_density_symbology = render_numeric_symbology_controls(
                "Current spatial-unit crash density",
                key_prefix="section7_current_spatial_density",
                default_method="Capped gradient",
            )

            original_density = st.session_state.get(
                "section7_original_density",
                None
            )

            crashes_for_map = st.session_state.get(
                "section7_crashes_for_map",
                crashes
            )

            crash_color_settings = {"enabled": False, "field": None}
            if "Crashes" in comparison_layers and crashes_for_map is not None and not crashes_for_map.empty:
                crash_color_settings = render_crash_color_controls(
                    crashes_for_map,
                    key_prefix="section7_crashes",
                )
                if crash_color_settings.get("enabled"):
                    field = crash_color_settings.get("field")
                    crash_color_settings["color_lookup"] = categorical_color_lookup(
                        crashes_for_map[field].fillna("Unknown")
                    )

            comparison_map = _make_segment_comparison_map(
                original_density=original_density,
                risk_segments=risk_segments_map,
                risk_corridors=risk_corridors_map,
                crashes=crashes_for_map,
                roads=roads_for_s7,
                roads_class=st.session_state.get("roads_class_display", None),
                signals=st.session_state.get("signals_clean", None),
                corridors=final_corridors,
                spatial_units=st.session_state.get("spatial_units_density_map", st.session_state.get("spatial_units", None)),
                selected_layers=comparison_layers,
                crash_density_symbology=current_density_symbology,
                original_density_symbology=original_density_symbology,
                risk_score_symbology=risk_score_symbology,
                crash_color_settings=crash_color_settings
            )

            st_folium(
                comparison_map,
                height=760,
                key=(
                    "section7_segment_comparison_map_"
                    + "_".join(comparison_layers)
                    + "_"
                    + str(len(risk_segments_map) if risk_segments_map is not None else 0)
                    + "_"
                    + str(len(risk_corridors_map) if risk_corridors_map is not None else 0)
                )
            )

