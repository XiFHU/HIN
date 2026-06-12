"""Shared workflow orchestration.

The individual Streamlit UI sections live in ui/steps/.
Analysis logic remains in the existing modules/ package.
"""

from .steps.roads import render_roads_step
from .steps.signals import render_signals_step
from .steps.corridors import render_corridors_step
from .steps.crashes import render_crashes_step
from .steps.results import render_results_step
from .steps.sliding_window import render_sliding_window_step


def render_workflow(spatial_unit, st_folium, workflow_context):
    """Render workflow sections for the selected spatial unit.

    Each major section is folded by default so the left workflow panel stays compact.
    Expand the section you are working on; the map remains visible on the right.
    """
    st = workflow_context["st"]

    st.markdown(f'<div class="workflow-label">{spatial_unit}</div>', unsafe_allow_html=True)

    with st.expander("Road Network", expanded=False):
        render_roads_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    if spatial_unit == "Intersection":
        with st.expander("OSM Signals / Signalized Intersections", expanded=False):
            render_signals_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    elif spatial_unit == "Corridor":
        with st.expander("OSM Signals", expanded=False):
            render_signals_step(st_folium, workflow_context, spatial_unit=spatial_unit)

        with st.expander("Corridors", expanded=False):
            render_corridors_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    elif spatial_unit == "Segment":
        with st.expander("OSM Signals", expanded=False):
            render_signals_step(st_folium, workflow_context, spatial_unit=spatial_unit)

        with st.expander("Corridors", expanded=False):
            render_corridors_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    with st.expander("Crash Data", expanded=False):
        render_crashes_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    with st.expander("Classification / Results", expanded=False):
        render_results_step(st_folium, workflow_context, spatial_unit=spatial_unit)

    if spatial_unit == "Segment":
        with st.expander("Sliding Window Risk Analysis", expanded=False):
            render_sliding_window_step(st_folium, workflow_context, spatial_unit=spatial_unit)
