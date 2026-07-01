"""Shared workflow orchestration for the simplified UI.

The analysis methods are unchanged. This file only regroups the UI so normal
users see the required workflow first, while technical thresholds stay inside
Optional settings expanders in each step.
"""

from .steps.roads import render_roads_step
from .steps.signals import render_signals_step
from .steps.corridors import render_corridors_step
from .steps.crashes import render_crashes_step
from .steps.results import render_results_step
from .steps.sliding_window import render_sliding_window_step
from .steps.visualization import render_visualization_step
from .steps.final_outputs import render_final_outputs_step


def _ready(st, key):
    value = st.session_state.get(key, None)
    return value is not None and not getattr(value, "empty", False)


def _workflow_status(st):
    roads_ready = _ready(st, "selected_roads")
    crashes_ready = _ready(st, "crashes")
    signals_ready = _ready(st, "signals_clean")
    corridors_ready = _ready(st, "corridors") or _ready(st, "final_corridors")
    results_ready = (
        _ready(st, "spatial_units_density_map")
        or _ready(st, "latest_results_units_table")
        or _ready(st, "kabco_result")
        or _ready(st, "section7_results")
    )

    st.caption(
        "Status: "
        + ("roads ready" if roads_ready else "roads needed")
        + " | "
        + ("crashes ready" if crashes_ready else "crashes needed")
        + " | "
        + ("results ready" if results_ready else "results not ready")
    )

    return {
        "roads": roads_ready,
        "crashes": crashes_ready,
        "signals": signals_ready,
        "corridors": corridors_ready,
        "results": results_ready,
    }


def render_workflow(spatial_unit, st_folium, workflow_context):
    """Render the simplified workflow for Intersection, Corridor, or Segment."""
    st = workflow_context["st"]
    status = _workflow_status(st)

    with st.expander("App limits and data quality notes", expanded=False):
        st.caption(
            "Large road/crash datasets can be slow, especially on Streamlit Cloud. "
            "Clip to the study boundary early, use road-class filters for very large OSM/TIGER networks, "
            "and avoid drawing huge result layers all at once. OSM traffic signals and road classes are crowd-sourced, "
            "so signal completeness and classification accuracy vary by location."
        )

    data_expanded = (
        not status["roads"]
        or bool(st.session_state.get("road_class_layer_enabled", False))
        or bool(st.session_state.get("keep_data_setup_open", False))
    )
    with st.expander("Data setup", expanded=data_expanded):
        render_roads_step(st_folium, workflow_context, spatial_unit=spatial_unit)
        render_crashes_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    if spatial_unit in ["Intersection", "Corridor"]:
        build_expanded = status["roads"] and not status["results"]
        with st.expander("Build spatial units", expanded=build_expanded):
            if spatial_unit == "Intersection":
                render_signals_step(st_folium, workflow_context, spatial_unit=spatial_unit)

            elif spatial_unit == "Corridor":
                render_signals_step(st_folium, workflow_context, spatial_unit=spatial_unit)
                render_corridors_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    analysis_expanded = status["roads"] and status["crashes"] and not status["results"]
    with st.expander("Analysis", expanded=analysis_expanded):
        if spatial_unit == "Segment":
            st.caption(
                "First create the segment crash-density layer, then run Sliding Window HIN. "
                "Crash-density maps remain available in Visualization."
            )
            render_results_step(st_folium, workflow_context, spatial_unit=spatial_unit)
            st.divider()
            st.session_state["defer_sliding_window_maps"] = True
            render_sliding_window_step(st_folium, workflow_context, spatial_unit=spatial_unit)
        else:
            render_results_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    with st.expander("Visualization", expanded=status["results"]):
        render_visualization_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    with st.expander("Results tables and downloads", expanded=status["results"]):
        render_final_outputs_step(workflow_context, spatial_unit=spatial_unit)
