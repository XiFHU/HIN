"""Corridor workflow UI."""

from .workflow_shared import render_workflow


def render_corridor_workflow(st_folium, workflow_context):
    return render_workflow(
        spatial_unit="Corridor",
        st_folium=st_folium,
        workflow_context=workflow_context,
    )
