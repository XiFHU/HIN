"""Intersection workflow UI."""

from .workflow_shared import render_workflow


def render_intersection_workflow(st_folium, workflow_context):
    return render_workflow(
        spatial_unit="Intersection",
        st_folium=st_folium,
        workflow_context=workflow_context,
    )
