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
    sliding_window_ui.__dict__.update(workflow_context)

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

    with f2:
        display_units, density_selection_summary = (
            sliding_window_ui._apply_ranked_selection_controls(
                display_units,
                selection_label="crash density",
                item_label="spatial units",
                all_option_label="All spatial units",
                key_prefix="crash_density_display",
                default_rank_col="CrashDensity",
                rank_candidates=[
                    "CrashDensity",
                    "CrashCount",
                    "Crash_Count",
                    "EPDO",
                    "KSI_Count",
                    "Fatal_Injury_Count",
                ],
                capture_candidates=[
                    "KSI_Count",
                    "Fatal_Injury_Count",
                    "CrashCount",
                    "Crash_Count",
                    "EPDO",
                ],
                analysis_help="This does not change the saved analysis results.",
            )
        )
    st.caption(density_selection_summary)

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


def _ensure_high_risk_score_column(gdf):
    """Add raw, non-normalized sliding-window score when missing."""
    if gdf is None:
        return gdf

    out = gdf.copy()

    if "HIN_Non_Normalized" in out.columns:
        raw_score = pd.to_numeric(
            out["HIN_Non_Normalized"],
            errors="coerce"
        ).fillna(0)
    elif "High_Risk_Score" in out.columns:
        raw_score = pd.to_numeric(
            out["High_Risk_Score"],
            errors="coerce"
        ).fillna(0)
        out["HIN_Non_Normalized"] = raw_score
    elif "Max_Window_Score" in out.columns:
        raw_score = pd.to_numeric(
            out["Max_Window_Score"],
            errors="coerce"
        ).fillna(0)
        out["HIN_Non_Normalized"] = raw_score
    else:
        raw_score = pd.Series(0.0, index=out.index)
        out["HIN_Non_Normalized"] = raw_score

    if "High_Risk_Score" not in out.columns:
        if "HIN_Non_Normalized" in out.columns:
            out["High_Risk_Score"] = pd.to_numeric(
                out["HIN_Non_Normalized"],
                errors="coerce"
            ).fillna(0)
        else:
            out["High_Risk_Score"] = 0

    out["High_Risk_Score"] = pd.to_numeric(
        out["High_Risk_Score"],
        errors="coerce"
    ).fillna(0)

    return out


def _hin_summary_metric_options(risk_segments_clean, preferred_metric):
    preferred = [
        preferred_metric,
        "HIN_Priority_Index",
        "HIN_Non_Normalized",
        "High_Risk_Score",
        "Max_Window_Score",
        "RiskScore",
        "CrashCount",
        "Crash_Count",
        "EPDO",
        "KSI_Count",
    ]

    numeric_cols = []
    for col in preferred:
        if col in risk_segments_clean.columns and col not in numeric_cols:
            numeric_cols.append(col)

    if not numeric_cols:
        numeric_cols = [
            c for c in risk_segments_clean.columns
            if c != "geometry"
            and pd.api.types.is_numeric_dtype(risk_segments_clean[c])
        ]

    return numeric_cols


def _apply_summary_statistic_filter(
    st,
    display_segments,
    metric,
    metric_values,
    threshold_base,
    summary_type,
    custom_threshold,
    label_prefix
):
    if summary_type == "Above average":
        threshold = float(threshold_base.mean()) if not threshold_base.empty else 0.0
        display_segments = display_segments[metric_values >= threshold].copy()
        st.caption(
            f"Showing {label_prefix} with {metric} >= positive-value average "
            f"({threshold:.2f})."
        )

    elif summary_type == "Above median":
        threshold = float(threshold_base.median()) if not threshold_base.empty else 0.0
        display_segments = display_segments[metric_values >= threshold].copy()
        st.caption(
            f"Showing {label_prefix} with {metric} >= positive-value median "
            f"({threshold:.2f})."
        )

    elif summary_type in [
        "25th percentile",
        "50th percentile / median",
        "75th percentile",
    ]:
        percentile_lookup = {
            "25th percentile": 0.25,
            "50th percentile / median": 0.50,
            "75th percentile": 0.75,
        }
        percentile_value = percentile_lookup[summary_type]
        threshold = (
            float(threshold_base.quantile(percentile_value))
            if not threshold_base.empty
            else 0.0
        )
        display_segments = display_segments[metric_values >= threshold].copy()
        st.caption(
            f"Showing {label_prefix} with {metric} >= {summary_type} "
            f"of positive values ({threshold:.2f})."
        )

    elif summary_type in [
        "IQR high-outlier threshold",
        "Above IQR high-outlier threshold",
    ]:
        if not threshold_base.empty:
            q1 = float(threshold_base.quantile(0.25))
            q3 = float(threshold_base.quantile(0.75))
            iqr = q3 - q1
            threshold = q3 + 1.5 * iqr
            display_segments = display_segments[metric_values >= threshold].copy()

            if display_segments.empty:
                threshold = q3
                display_segments = display_segments.iloc[0:0].copy()
                fallback_segments = metric_values >= threshold
                st.caption(
                    "IQR high-outlier threshold selected no segments/windows, "
                    "so the map is using Q3 instead. "
                    f"Showing {metric} >= Q3 ({threshold:.2f})."
                )
                return fallback_segments, threshold, "mask"

            st.caption(
                f"Showing {label_prefix} with {metric} >= IQR high-outlier "
                f"threshold Q3 + 1.5 × IQR ({threshold:.2f})."
            )
        else:
            threshold = 0.0
            display_segments = display_segments[metric_values >= threshold].copy()
            st.caption(
                f"No valid {metric} values were available for IQR; "
                f"showing {metric} >= 0.00."
            )

    elif summary_type in [
        "IQR low-outlier threshold",
        "Below IQR low-outlier threshold",
    ]:
        if not threshold_base.empty:
            q1 = float(threshold_base.quantile(0.25))
            q3 = float(threshold_base.quantile(0.75))
            iqr = q3 - q1
            threshold = q1 - 1.5 * iqr
            display_segments = display_segments[metric_values <= threshold].copy()
            st.caption(
                f"Showing {label_prefix} with {metric} <= IQR low-outlier "
                f"threshold Q1 - 1.5 × IQR ({threshold:.2f})."
            )
        else:
            threshold = 0.0
            display_segments = display_segments[metric_values <= threshold].copy()
            st.caption(
                f"No valid {metric} values were available for IQR; "
                f"showing {metric} <= 0.00."
            )

    elif summary_type in [
        "Median + 1.5 × IQR threshold",
        "Above median + 1.5 × IQR threshold",
    ]:
        if not threshold_base.empty:
            q1 = float(threshold_base.quantile(0.25))
            q3 = float(threshold_base.quantile(0.75))
            median_value = float(threshold_base.median())
            iqr = q3 - q1
            threshold = median_value + 1.5 * iqr
            display_segments = display_segments[metric_values >= threshold].copy()

            if display_segments.empty:
                threshold = median_value
                display_segments = display_segments.iloc[0:0].copy()
                fallback_segments = metric_values >= threshold
                st.caption(
                    "Median + 1.5 × IQR threshold selected no segments/windows, "
                    "so the map is using the median instead. "
                    f"Showing {metric} >= median ({threshold:.2f})."
                )
                return fallback_segments, threshold, "mask"

            st.caption(
                f"Showing {label_prefix} with {metric} >= Median + 1.5 × IQR "
                f"threshold ({threshold:.2f})."
            )
        else:
            threshold = 0.0
            display_segments = display_segments[metric_values >= threshold].copy()
            st.caption(
                f"No valid {metric} values were available for IQR; "
                f"showing {metric} >= 0.00."
            )

    elif summary_type == "Custom threshold":
        threshold = float(custom_threshold if custom_threshold is not None else 0.0)
        display_segments = display_segments[metric_values >= threshold].copy()
        st.caption(f"Showing {label_prefix} with {metric} >= {threshold:.2f}.")

    else:
        threshold = None
        st.caption(f"Showing {metric} value map for all {label_prefix}.")

    return display_segments, threshold, "gdf"


def _render_score_summary_visualization(
    st_folium,
    workflow_context,
    preferred_metric,
    metric_label,
    layer_name,
    key_prefix,
):
    """Shared threshold/summary map for normalized HIN or raw High Risk Score.

    The selected sliding-window analysis already determines whether the score
    is Crash Count based or EPDO based, so this map should not show another
    summary-metric dropdown. It only lets the user choose the summary statistic
    or threshold applied to the current result.
    """
    globals().update(workflow_context)
    sliding_window_ui.__dict__.update(workflow_context)

    results = st.session_state.get(
        "section7_results",
        None
    )

    if results is None:
        st.info(
            "Run Sliding Window Risk Analysis first. Then the threshold/summary "
            "map will appear here."
        )
        return

    risk_segments = results.get("risk_segments")

    if risk_segments is None or getattr(risk_segments, "empty", True):
        st.info("No HIN segment/window results are available yet.")
        return

    final_corridors = st.session_state.get(
        "final_corridors",
        st.session_state.get("corridors", None)
    )

    selected_roads = st.session_state.get(
        "selected_roads",
        None
    )

    route_col_s7 = st.session_state.get(
        "section7_route_col_s7",
        st.session_state.get("route_col", "FULLNAME")
    )

    risk_corridors = results.get("risk_corridors")

    risk_segments = sliding_window_ui._ensure_hin_priority_columns(
        risk_segments
    )

    risk_segments = _ensure_high_risk_score_column(
        risk_segments
    )

    risk_segments_clean = section7_clean_risk_segments(
        risk_segments,
        route_col_s7
    )

    risk_segments_clean = _ensure_high_risk_score_column(
        risk_segments_clean
    )

    if preferred_metric not in risk_segments_clean.columns:
        st.warning(
            f"{preferred_metric} is not available in the current "
            "sliding-window result."
        )
        return

    if risk_corridors is not None:
        risk_corridors_clean = section7_clean_risk_corridors(
            risk_corridors,
            route_col_s7
        )
    else:
        risk_corridors_clean = None

    metric = preferred_metric

    c1, c2 = st.columns([0.35, 0.65])

    with c1:
        summary_type = st.selectbox(
            f"{metric_label} summary statistic",
            [
                "Value map",
                "Above average",
                "Above median",
                "25th percentile",
                "50th percentile / median",
                "75th percentile",
                "Above IQR high-outlier threshold",
                "Below IQR low-outlier threshold",
                "Above median + 1.5 × IQR threshold",
                "Custom threshold",
            ],
            key=f"{key_prefix}_type_v3",
        )

        custom_threshold = None

        if summary_type == "Custom threshold":
            values = pd.to_numeric(
                risk_segments_clean[metric],
                errors="coerce"
            )

            positive_values = values[
                values > 0
            ]

            threshold_base = (
                positive_values
                if not positive_values.empty
                else values.dropna()
            )

            default_threshold = (
                float(threshold_base.median())
                if not threshold_base.empty
                else 0.0
            )

            custom_threshold = st.number_input(
                f"Minimum {metric_label} value",
                value=default_threshold,
                step=5.0,
                key=f"{key_prefix}_custom_threshold",
            )

    st.caption(
        f"{metric_label} summary uses the current sliding-window analysis result."
    )

    display_segments = risk_segments_clean.copy()

    metric_values = pd.to_numeric(
        display_segments[metric],
        errors="coerce"
    )

    valid_metric_values = metric_values.dropna()

    positive_metric_values = valid_metric_values[
        valid_metric_values > 0
    ]

    threshold_base = (
        positive_metric_values
        if not positive_metric_values.empty
        else valid_metric_values
    )

    filtered, threshold, filter_type = _apply_summary_statistic_filter(
        st=st,
        display_segments=display_segments,
        metric=metric,
        metric_values=metric_values,
        threshold_base=threshold_base,
        summary_type=summary_type,
        custom_threshold=custom_threshold,
        label_prefix="HIN segments/windows",
    )

    if filter_type == "mask":
        display_segments = risk_segments_clean[
            filtered
        ].copy()
    else:
        display_segments = filtered

    if display_segments.empty:
        st.warning(
            "No HIN segments/windows match the selected summary threshold."
        )
        return

    risk_corridors_map = risk_corridors_clean

    if (
        display_segments is not None
        and not display_segments.empty
        and risk_corridors_clean is not None
        and not risk_corridors_clean.empty
        and "CorridorID" in display_segments.columns
        and "CorridorID" in risk_corridors_clean.columns
    ):
        selected_corridor_ids = set(
            display_segments["CorridorID"].astype(str)
        )

        risk_corridors_map = risk_corridors_clean[
            risk_corridors_clean["CorridorID"]
            .astype(str)
            .isin(selected_corridor_ids)
        ].copy()

    with st.expander(
        f"{metric_label} summary map color / legend settings",
        expanded=False
    ):
        risk_score_symbology = render_numeric_symbology_controls(
            f"{metric_label} summary map",
            key_prefix=f"viz_{key_prefix}_map",
            default_method="Quantile",
        )

    selected_layers = [
        layer_name
    ]

    fmap = sliding_window_ui._make_segment_comparison_map(
        original_density=st.session_state.get(
            "section7_original_density",
            None
        ),
        risk_segments=display_segments,
        risk_corridors=risk_corridors_map,
        crashes=st.session_state.get(
            "section7_crashes_for_map",
            st.session_state.get("crashes", None)
        ),
        roads=selected_roads,
        roads_class=st.session_state.get(
            "roads_class_display",
            None
        ),
        signals=st.session_state.get(
            "signals_clean",
            None
        ),
        corridors=final_corridors,
        spatial_units=st.session_state.get(
            "spatial_units_density_map",
            st.session_state.get("spatial_units", None)
        ),
        selected_layers=selected_layers,
        crash_density_symbology={
            "method": "Capped gradient"
        },
        original_density_symbology={
            "method": "Capped gradient"
        },
        risk_score_symbology=risk_score_symbology,
        crash_color_settings={
            "enabled": False,
            "field": None
        },
    )

    st_folium(
        fmap,
        height=760,
        width="100%",
        key=(
            f"viz_{key_prefix}_map_"
            + str(summary_type)
            + "_"
            + str(metric)
            + "_"
            + str(len(display_segments))
        ),
    )


def _render_hin_summary_visualization(st_folium, workflow_context):
    """Display-only HIN threshold/summary map using normalized 0-100 index."""
    _render_score_summary_visualization(
        st_folium=st_folium,
        workflow_context=workflow_context,
        preferred_metric="HIN_Priority_Index",
        metric_label="HIN",
        layer_name="HIN Priority Index",
        key_prefix="hin_summary_map",
    )


def _render_high_risk_visualization(st_folium, workflow_context):
    """Display raw, non-normalized sliding-window High Risk Score map."""
    globals().update(workflow_context)
    sliding_window_ui.__dict__.update(workflow_context)

    results = st.session_state.get("section7_results", None)
    if results is None:
        st.info("Run Sliding Window Risk Analysis first. Then the High Risk Score map will appear here.")
        return

    final_corridors = st.session_state.get("final_corridors", st.session_state.get("corridors", None))
    selected_roads = st.session_state.get("selected_roads", None)
    route_col_s7 = st.session_state.get("section7_route_col_s7", st.session_state.get("route_col", "FULLNAME"))

    risk_segments = sliding_window_ui._ensure_hin_priority_columns(results["risk_segments"])
    risk_segments = _ensure_high_risk_score_column(risk_segments)
    risk_segments_clean = section7_clean_risk_segments(risk_segments, route_col_s7)
    risk_segments_clean = _ensure_high_risk_score_column(risk_segments_clean)

    risk_corridors = results.get("risk_corridors")
    risk_corridors_clean = section7_clean_risk_corridors(risk_corridors, route_col_s7) if risk_corridors is not None else None

    f1, f2 = st.columns([0.24, 0.76])
    with f1:
        min_crash_count = st.number_input(
            "Minimum crash count",
            min_value=0,
            value=0,
            step=1,
            key="viz_high_risk_min_crash_count",
            help="Display-only filter. It does not rerun sliding-window analysis."
        )

    risk_segments_clean = _filter_by_crash_count(risk_segments_clean, min_crash_count)
    if risk_segments_clean is None or risk_segments_clean.empty:
        st.warning("No High Risk Score segments remain after the map filter. Lower the minimum crash count.")
        return

    with f2:
        risk_segments_map, high_risk_selection_summary = (
            sliding_window_ui._apply_ranked_selection_controls(
                risk_segments_clean,
                selection_label="High Risk Score",
                item_label="segments",
                all_option_label="All High Risk Score segments",
                key_prefix="high_risk_display",
                default_rank_col="HIN_Non_Normalized",
                rank_candidates=[
                    "HIN_Non_Normalized",
                    "High_Risk_Score",
                    "Max_Window_Score",
                    "Crash_Count",
                    "EPDO",
                    "KSI_Count",
                    "Fatal_Injury_Count",
                ],
                capture_candidates=[
                    "KSI_Count",
                    "Fatal_Injury_Count",
                    "Crash_Count",
                    "EPDO",
                    "Max_Window_Score",
                ],
                analysis_help="This does not rerun the sliding-window analysis.",
            )
        )
    st.caption(high_risk_selection_summary)

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

    with st.expander("Optional High Risk Score map style", expanded=False):
        risk_score_symbology = render_numeric_symbology_controls(
            "High Risk Score",
            key_prefix="viz_section7_high_risk_score",
            default_method="Quantile",
        )

    selected_layers = ["High Risk Score"]
    fmap = sliding_window_ui._make_segment_comparison_map(
        original_density=st.session_state.get("section7_original_density", None),
        risk_segments=risk_segments_map,
        risk_corridors=risk_corridors_map,
        crashes=st.session_state.get("section7_crashes_for_map", st.session_state.get("crashes", None)),
        roads=selected_roads,
        roads_class=st.session_state.get("roads_class_display", None),
        signals=st.session_state.get("signals_clean", None),
        corridors=final_corridors,
        spatial_units=st.session_state.get("spatial_units_density_map", st.session_state.get("spatial_units", None)),
        selected_layers=selected_layers,
        crash_density_symbology={"method": "Capped gradient"},
        original_density_symbology={"method": "Capped gradient"},
        risk_score_symbology=risk_score_symbology,
        crash_color_settings={"enabled": False, "field": None},
    )

    st_folium(
        fmap,
        height=760,
        width="100%",
        key=(
            "viz_section7_high_risk_score_map_"
            + str(len(risk_segments_map) if risk_segments_map is not None else 0)
        ),
    )


def _render_high_risk_summary_visualization(st_folium, workflow_context):
    """Display raw, non-normalized High Risk Score threshold/summary map."""
    _render_score_summary_visualization(
        st_folium=st_folium,
        workflow_context=workflow_context,
        preferred_metric="HIN_Non_Normalized",
        metric_label="High Risk Score",
        layer_name="High Risk Score",
        key_prefix="high_risk_summary_map",
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
        available_maps.append("HIN Threshold/Summary Map")
        available_maps.append("High Risk Score Map")
        available_maps.append("High Risk Score Threshold/Summary Map")

    if not available_maps:
        st.info("Run an analysis first. Visualization maps will appear here after results are available.")
        return

    selected_map = st.selectbox(
        "Map to display",
        available_maps,
        key="visualization_selected_map",
        help="Crash Density Map and HIN Priority Index Map show the main result values. The threshold/summary maps use the same existing results but let you highlight units above the average, median, or a custom threshold for quick screening."
    )
    if selected_map == "Crash Density Map":
        st.caption("Crash Density Map = the main result map showing each intersection/segment/corridor by its calculated crash density value.")
    elif selected_map == "Crash Density Threshold/Summary Map":
        st.caption("Crash Density Threshold/Summary Map = a screening view from the same data, such as only units above the average or median. It does not create new analysis results.")
    elif selected_map == "HIN Threshold/Summary Map":
        st.caption("HIN Threshold/Summary Map = a screening view from existing HIN results, such as HIN index above average, median, percentile, IQR, or a custom threshold. It does not recalculate HIN scores.")
    elif selected_map == "High Risk Score Map":
        st.caption("High Risk Score Map = the raw, non-normalized sliding-window score. For Crash Count it is the maximum overlapping window crash count; for EPDO it is the maximum overlapping window EPDO.")
    elif selected_map == "High Risk Score Threshold/Summary Map":
        st.caption("High Risk Score Threshold/Summary Map = a screening view using the raw non-normalized sliding-window score with the same summary metric/statistic controls as the HIN threshold map.")

    if selected_map == "Crash Density Map":
        _render_crash_density_visualization(st_folium, workflow_context)
    elif selected_map == "Crash Density Threshold/Summary Map":
        _render_summary_visualization(st_folium, workflow_context)
    elif selected_map == "HIN Priority Index Map":
        _render_sliding_window_visualization(st_folium, workflow_context)
    elif selected_map == "HIN Threshold/Summary Map":
        _render_hin_summary_visualization(st_folium, workflow_context)
    elif selected_map == "High Risk Score Map":
        _render_high_risk_visualization(st_folium, workflow_context)
    elif selected_map == "High Risk Score Threshold/Summary Map":
        _render_high_risk_summary_visualization(st_folium, workflow_context)
