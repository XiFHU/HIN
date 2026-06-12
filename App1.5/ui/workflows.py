"""Workflow dispatcher.

This file is now intentionally small. Each spatial-unit tab has its own file:
- ui/intersection.py
- ui/corridor.py
- ui/segment.py

The large shared implementation is temporarily kept in ui/workflow_shared.py.
Next refactor step: move shared Step 1, Step 4, results, and downloads into ui/steps/.
"""

from .intersection import render_intersection_workflow
from .corridor import render_corridor_workflow
from .segment import render_segment_workflow


def render_workflow(spatial_unit, st_folium, workflow_context):
    if spatial_unit == "Intersection":
        return render_intersection_workflow(st_folium, workflow_context)

    if spatial_unit == "Corridor":
        return render_corridor_workflow(st_folium, workflow_context)

    if spatial_unit == "Segment":
        return render_segment_workflow(st_folium, workflow_context)

    raise ValueError(f"Unknown spatial unit: {spatial_unit}")
