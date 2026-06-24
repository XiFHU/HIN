"""Unified visualization section for result maps.

This section intentionally changes display copies only. It does not overwrite
analysis result tables or rerun crash assignment / sliding windows.
"""

from .results import make_density_colormap
import pandas as pd
import geopandas as gpd
from shapely.geometry import box, shape
from .downloads import render_results_downloads
from ..map_symbology import render_numeric_symbology_controls, render_crash_color_controls, categorical_color_lookup
import ui.steps.sliding_window as sliding_window_ui


def _filter_by_crash_count(gdf, min_crash_count):
    if gdf is None or getattr(gdf, "empty", True) or min_crash_count <= 0:
        return gdf
    out = gdf.copy()
    for col in ["CrashCount", "Crash_Count"]:
        if col in out.columns:
            values = pd.to_numeric(out[col], errors="coerce").fillna(0)
            return out[values >= int(min_crash_count)].copy()
    return out





def _render_crash_density_visualization(st_folium, workflow_context):
    globals().update(workflow_context)

    spatial_units_map = st.session_state.get("spatial_units_density_map", None)
    assigned_crashes = st.session_state.get("assigned_crashes", None)
    analysis_type = st.session_state.get("analysis_type", "Spatial Units")
    kabco_result = st.session_state.get("kabco_result", None)

    if spatial_units_map is None or assigned_crashes is None:
        st.info("Run Classification / Results first. Then the crash-density map will appear here.")
        return

    f1, f2 = st.columns([0.28, 0.72])
    with f1:
        min_crash_count = st.number_input(
            "Minimum crash count",
            min_value=0,
            value=0,
            step=1,
            key="viz_density_min_crash_count",
            help="Display-only filter. It does not change the saved analysis result table."
        )

    display_units = _filter_by_crash_count(spatial_units_map, min_crash_count)

    if display_units is None or display_units.empty:
        st.warning("No spatial units remain after the map filter. Lower the minimum crash count.")
        return


    units_table = st.session_state.get("latest_results_units_table")
    if units_table is None:
        units_table = display_units.drop(columns="geometry", errors="ignore")

    assigned_table = st.session_state.get("latest_results_assigned_table")
    if assigned_table is None:
        assigned_table = assigned_crashes.drop(columns="geometry", errors="ignore")

    density_symbology_settings = render_numeric_symbology_controls(
        "Crash density",
        key_prefix=f"viz_results_crash_density_{analysis_type}",
        default_method="Capped gradient",
    )
    density_cmap = make_density_colormap(
        display_units,
        pd,
        cm,
        settings=density_symbology_settings,
    )

    render_results_downloads(
        st_folium=st_folium,
        workflow_context=workflow_context,
        spatial_units_map=display_units,
        units_table=units_table,
        assigned_table=assigned_table,
        assigned_crashes=assigned_crashes,
        kabco_result=kabco_result,
        analysis_type=analysis_type,
        density_cmap=density_cmap,
        render_map=True,
    )


def _render_sliding_window_visualization(st_folium, workflow_context):
    globals().update(workflow_context)
    sliding_window_ui.__dict__.update(workflow_context)

    results = st.session_state.get("section7_results", None)
    if results is None:
        st.info("Run Sliding Window Risk Analysis first. Then the HIN map will appear here.")
        return

    final_corridors = st.session_state.get("final_corridors", st.session_state.get("corridors", None))
    selected_roads = st.session_state.get("selected_roads", None)
    route_col_s7 = st.session_state.get("section7_route_col_s7", st.session_state.get("route_col", "FULLNAME"))

    risk_segments = sliding_window_ui._ensure_hin_priority_columns(results["risk_segments"])
    risk_corridors = results["risk_corridors"]
    risk_segments_clean = section7_clean_risk_segments(risk_segments, route_col_s7)
    risk_corridors_clean = section7_clean_risk_corridors(risk_corridors, route_col_s7)

    f1, f2 = st.columns([0.24, 0.76])
    with f1:
        min_crash_count = st.number_input(
            "Minimum crash count",
            min_value=0,
            value=0,
            step=1,
            key="viz_hin_min_crash_count",
            help="Display-only filter. It does not rerun sliding-window analysis."
        )

    risk_segments_clean = _filter_by_crash_count(risk_segments_clean, min_crash_count)

    if risk_segments_clean is None or risk_segments_clean.empty:
        st.warning("No HIN segments remain after the map filter. Lower the minimum crash count.")
        return

    _render_area_selection_summary(risk_segments_clean, "viz_hin_area")

    with f2:
        risk_segments_map, hin_selection_summary = sliding_window_ui._apply_hin_selection_controls(risk_segments_clean)
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

    selected_layers = ["HIN Priority Index"]

    with st.expander("Optional HIN map style", expanded=False):
        risk_score_symbology = render_numeric_symbology_controls(
            "HIN priority index",
            key_prefix="viz_section7_hin_risk_score",
            default_method="Quantile",
        )
    original_density_symbology = {"method": "Capped gradient"}
    current_density_symbology = {"method": "Capped gradient"}

    crashes_for_map = st.session_state.get("section7_crashes_for_map", st.session_state.get("crashes", None))
    crash_color_settings = {"enabled": False, "field": None}
    if "Crashes" in selected_layers and crashes_for_map is not None and not crashes_for_map.empty:
        crash_color_settings = render_crash_color_controls(
            crashes_for_map,
            key_prefix="viz_section7_crashes",
        )
        if crash_color_settings.get("enabled"):
            field = crash_color_settings.get("field")
            crash_color_settings["color_lookup"] = categorical_color_lookup(
                crashes_for_map[field].fillna("Unknown")
            )

    fmap = sliding_window_ui._make_segment_comparison_map(
        original_density=st.session_state.get("section7_original_density", None),
        risk_segments=risk_segments_map,
        risk_corridors=risk_corridors_map,
        crashes=crashes_for_map,
        roads=selected_roads,
        roads_class=st.session_state.get("roads_class_display", None),
        signals=st.session_state.get("signals_clean", None),
        corridors=final_corridors,
        spatial_units=st.session_state.get("spatial_units_density_map", st.session_state.get("spatial_units", None)),
        selected_layers=selected_layers,
        crash_density_symbology=current_density_symbology,
        original_density_symbology=original_density_symbology,
        risk_score_symbology=risk_score_symbology,
        crash_color_settings=crash_color_settings,
    )

    hin_map_result = st_folium(
        fmap,
        height=760,
        width="100%",
        key=(
            "viz_section7_segment_comparison_map_"
            + "_".join(selected_layers)
            + "_"
            + str(len(risk_segments_map) if risk_segments_map is not None else 0)
            + "_"
            + str(len(risk_corridors_map) if risk_corridors_map is not None else 0)
        ),
    )



def _render_summary_visualization(st_folium, workflow_context):
    globals().update(workflow_context)
    units = st.session_state.get("spatial_units_density_map", None)
    if units is None or getattr(units, "empty", True):
        st.info("Run crash-density analysis first. Then summary maps will appear here.")
        return
    numeric_cols = [c for c in ["CrashDensity", "CrashCount", "EPDO", "KSI_Count", "Fatal_Injury_Count", "HIN_Priority_Index"] if c in units.columns]
    if not numeric_cols:
        st.warning("No numeric crash-density fields are available for summary mapping.")
        return
    c1, c2 = st.columns([0.35, 0.65])
    with c1:
        metric = st.selectbox("Summary metric", numeric_cols, key="summary_map_metric")
        summary_type = st.selectbox("Summary statistic", ["Value map", "Above average", "Above median"], key="summary_map_type")
    display_units = units.copy()
    if summary_type == "Above average":
        threshold = pd.to_numeric(display_units[metric], errors="coerce").mean()
        display_units = display_units[pd.to_numeric(display_units[metric], errors="coerce") >= threshold].copy()
        st.caption(f"Showing units with {metric} >= average ({threshold:.2f}).")
    elif summary_type == "Above median":
        threshold = pd.to_numeric(display_units[metric], errors="coerce").median()
        display_units = display_units[pd.to_numeric(display_units[metric], errors="coerce") >= threshold].copy()
        st.caption(f"Showing units with {metric} >= median ({threshold:.2f}).")
    else:
        st.caption(f"Showing {metric} value map.")
    sym = render_numeric_symbology_controls("Summary map", key_prefix="viz_summary_map", default_method="Quantile")
    cmap = make_density_colormap(display_units, pd, cm, settings=sym)
    render_results_downloads(
        st_folium=st_folium,
        workflow_context=workflow_context,
        spatial_units_map=display_units,
        units_table=display_units.drop(columns="geometry", errors="ignore"),
        assigned_table=st.session_state.get("latest_results_assigned_table", pd.DataFrame()),
        assigned_crashes=st.session_state.get("assigned_crashes", pd.DataFrame()),
        kabco_result=st.session_state.get("kabco_result", None),
        analysis_type="Summary Map",
        density_cmap=cmap,
        render_map=True,
    )

def render_visualization_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    st.markdown("**Choose a result map**")
    available_maps = []

    if st.session_state.get("spatial_units_density_map", None) is not None:
        available_maps.append("Crash Density Map")
        available_maps.append("Crash Density Threshold/Summary Map")

    if st.session_state.get("section7_results", None) is not None:
        available_maps.append("HIN Priority Index Map")

    if not available_maps:
        st.info("Run an analysis first. Visualization maps will appear here after results are available.")
        return

    selected_map = st.selectbox(
        "Map to display",
        available_maps,
        key="visualization_selected_map",
        help="Crash Density Map shows the actual crash density values for each spatial unit. Crash Density Threshold/Summary Map uses the same results but lets you highlight units above the average or median for quick screening."
    )
    if selected_map == "Crash Density Map":
        st.caption("Crash Density Map = the main result map showing each intersection/segment/corridor by its calculated crash density value.")
    elif selected_map == "Crash Density Threshold/Summary Map":
        st.caption("Crash Density Threshold/Summary Map = a screening view from the same data, such as only units above the average or median. It does not create new analysis results.")

    if selected_map == "Crash Density Map":
        _render_crash_density_visualization(st_folium, workflow_context)
    elif selected_map == "Crash Density Threshold/Summary Map":
        _render_summary_visualization(st_folium, workflow_context)
    elif selected_map == "HIN Priority Index Map":
        _render_sliding_window_visualization(st_folium, workflow_context)
