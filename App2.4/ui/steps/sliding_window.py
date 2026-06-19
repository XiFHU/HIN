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
                    "Max_Risk_Score",
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

    if "HIN Risk Score" in selected_layers or "Risk Segments" in selected_layers:
        risk_segments = clean_for_map(risk_segments)

        if risk_segments is not None and not risk_segments.empty:
            risk_segments = make_map_safe_gdf(
                risk_segments,
                numeric_cols=[
                    "Risk_Score",
                    "CrashCount",
                    "EPDO",
                    "Length_Miles"
                ]
            )

            values = pd.to_numeric(
                risk_segments["Risk_Score"],
                errors="coerce"
            ).fillna(0)

            risk_cmap = make_numeric_colormap(
                values,
                cm,
                "HIN Risk Score",
                settings=risk_score_symbology,
            )

            def style_risk_segment(feature):
                value = feature["properties"].get("Risk_Score", 0)
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
                    "Risk_Score",
                    "CrashCount",
                    "EPDO",
                    "FromMile",
                    "ToMile"
                ]
                if c in risk_segments.columns
            ]

            folium.GeoJson(
                make_json_safe_gdf(risk_segments),
                name="HIN Risk Score",
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

    if selected_roads is None:
        st.warning("Please upload/select roads first.")

    elif crashes is None:
        st.warning("Please upload crash data first.")

    else:
        with st.expander("Analysis Settings", expanded=True):

            route_col_s7 = st.selectbox(
                "Route name column",
                options=list(selected_roads.columns),
                index=list(selected_roads.columns).index("FULLNAME")
                if "FULLNAME" in selected_roads.columns
                else 0,
                key="section7_route_col"
            )

            segment_id_col_s7 = st.session_state.get(
                "segment_id_col",
                None
            )

            st.markdown("**Sliding-window method summary**")
            st.info(
                "This step ranks roads with a moving window. Uploaded or OSM road lines are used as "
                "the route network. The sliding window has a fixed length and moves along each route "
                "by the window increment. Each output segment receives the highest window score from "
                "any sliding window that overlaps it. The output segment geometry can be based on the "
                "original uploaded segments, a user-defined equal segment length, or the window increment."
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
                help="This controls the final HIN Risk Score line segments shown on the map. It does not change how crashes are counted inside each sliding window."
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
                    The HIN Risk Score is based on the selected risk metric. If the metric is Crash Count, the score is the maximum overlapping window crash count. If the metric is EPDO, the score is the maximum overlapping window severity-weighted total. The top-percent threshold is then applied to those final segment scores.
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
                st.caption(
                    "Final map segments use this equal-length value. The sliding window length and increment still control how window scores are calculated."
                )

            elif segmentation_method == "Use window-increment segments":
                segment_length = step_len
                st.caption(
                    "Final map segments equal the window increment. For example, a 0.50-mile window and 0.10-mile increment displays 0.10-mile HIN segments, each scored from overlapping 0.50-mile windows."
                )

            else:
                segment_length = step_len
                st.caption(
                    "Final map segments use the existing uploaded/OSM road geometry. Segment lengths may vary. The window increment controls only how far the sliding window moves between scores."
                )

            col4, col5 = st.columns(2)

            with col4:
                top_percent = st.slider(
                    "Risk threshold (top %)",
                    min_value=1,
                    max_value=50,
                    value=10,
                    step=1,
                    key="section7_top_percent"
                )

            with col5:
                crash_snap_dist_ft = st.number_input(
                    "Crash-to-route search distance (feet)",
                    min_value=10.0,
                    value=150.0,
                    step=10.0,
                    key="section7_crash_snap_dist_ft"
                )

            risk_metric = st.radio(
                "Risk Metric",
                [
                    "Crash Count",
                    "EPDO"
                ],
                horizontal=True,
                key="section7_risk_metric"
            )

            with st.expander("Optional minimum crash count filter", expanded=False):
                st.caption(
                    "Use this optional filter to remove low-crash HIN output segments before "
                    "the final top-percent risky segment selection, map display, and downloads. "
                    "Leave it off to keep every output segment, including zero-crash segments."
                )
                enable_min_crash_filter_s7 = st.checkbox(
                    "Exclude HIN output segments with fewer than a minimum number of crashes",
                    value=False,
                    key="section7_enable_min_crash_filter",
                )
                min_crash_count_s7 = st.number_input(
                    "Minimum crash count",
                    min_value=0,
                    value=1,
                    step=1,
                    key="section7_min_crash_count",
                    help=(
                        "Editable integer threshold. For example, 1 removes only zero-crash segments; "
                        "3 keeps segments with 3 or more crashes; any other non-negative value can be entered."
                    ),
                    disabled=not enable_min_crash_filter_s7,
                )

            with st.expander("Metric definitions", expanded=True):
                st.markdown(
                    """
                    **How the HIN Risk Score is calculated**

                    1. Crashes are snapped to the nearest selected route within the crash-to-route search distance.
                    2. A fixed-length sliding window moves along each route.
                    3. Each window receives a score.
                    4. Each short output segment receives the highest score from the windows that overlap it.
                    5. Segments at or above the selected top-percent threshold are flagged as risky.

                    **Crash Count vs. EPDO**

                    - **Crash Count** counts every crash as 1. A fatal crash, injury crash, and PDO/no-injury crash have the same weight.
                    - **EPDO** is a severity-weighted crash score. Each crash is converted to a weighted value using the K/A/B/C/O weights below, then the weights are summed in each sliding window.
                    - **HIN Risk Score** is the final score assigned to each output segment. If the selected metric is Crash Count, the HIN Risk Score is based on the maximum overlapping window crash count. If the selected metric is EPDO, the HIN Risk Score is based on the maximum overlapping window EPDO total.
                    - **Optional minimum crash count filter** removes output segments with fewer than the entered number of crashes before the final top-percent risky segment selection. For example, a value of 1 removes zero-crash segments, while a value of 4 keeps only segments with 4 or more crashes.

                    Density metrics are not used in the sliding-window selector because fixed-length windows make density and count-based maps nearly identical. Use the final comparison map to compare HIN risk against the original crash-density layer.
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
                roads=selected_roads,
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
                min_crash_count=(
                    int(min_crash_count_s7)
                    if enable_min_crash_filter_s7
                    else None
                )
            )

            original_density = _build_original_crash_density_layer(
                selected_roads,
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
            risk_segments = results["risk_segments"]
            risk_corridors = results["risk_corridors"]
            route_lines = results["route_lines"]
            risk_threshold = results["risk_threshold"]

            st.info(
                f"Risk threshold value: {risk_threshold:.3f}"
            )

            applied_min_crash_filter = st.session_state.get(
                "section7_enable_min_crash_filter",
                False
            )
            applied_min_crash_count = st.session_state.get(
                "section7_min_crash_count",
                1
            )
            if applied_min_crash_filter:
                st.info(
                    f"Minimum crash count filter applied: HIN output segments with "
                    f"Crash_Count < {int(applied_min_crash_count)} were removed before "
                    "the final risky segment selection and map display."
                )

            risk_segments_clean = section7_clean_risk_segments(
                risk_segments,
                route_col_s7
            )

            risk_corridors_clean = section7_clean_risk_corridors(
                risk_corridors,
                route_col_s7
            )

            seg_table = (
                risk_segments_clean
                .drop(columns="geometry", errors="ignore")
                .sort_values(
                    "Risk_Score",
                    ascending=False
                )
            )

            corridor_table = (
                risk_corridors_clean
                .drop(columns="geometry", errors="ignore")
                .sort_values(
                    "Max_Risk_Score",
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
                        file_name="section7_risk_segments.csv",
                        mime="text/csv",
                        key="section7_download_segments_csv"
                    )

                    st.download_button(
                        "Sliding Window Risk Segments GeoJSON",
                        data=gdf_to_geojson_bytes(
                            risk_segments_clean
                        ),
                        file_name="section7_sliding_window_risk_segments.geojson",
                        mime="application/geo+json",
                        key="section7_download_segments_geojson"
                    )

                    st.download_button(
                        "Section 7 Excel",
                        data=section7_excel_bytes(
                            risk_windows,
                            risk_segments_clean,
                            risk_corridors_clean
                        ),
                        file_name="section7_sliding_window_results.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="section7_download_excel"
                    )

                    st.download_button(
                        "Risk Corridors CSV",
                        data=df_to_csv_bytes(
                            corridor_table
                        ),
                        file_name="section7_risk_corridors.csv",
                        mime="text/csv",
                        key="section7_download_corridors_csv"
                    )

            # -----------------------------
            # Final Segment Comparison Map
            # -----------------------------

            comparison_layer_options = [
                "HIN Risk Score",
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
                "HIN Risk Score",
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

            risk_score_symbology = render_numeric_symbology_controls(
                "HIN risk score",
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
                risk_segments=risk_segments_clean,
                risk_corridors=risk_corridors_clean,
                crashes=crashes_for_map,
                roads=selected_roads,
                roads_class=st.session_state.get("roads_class_display", None),
                signals=st.session_state.get("signals_clean", None),
                corridors=st.session_state.get("corridors", None),
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
                    + str(len(risk_segments_clean))
                    + "_"
                    + str(len(risk_corridors_clean))
                )
            )

