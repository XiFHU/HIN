"""Compact GIS layer selector for the HIN app."""

import streamlit as st

DEFAULT_LAYERS = {
    "Boundary": False,
    "Roads": True,
    "Roads by Class/Type": False,
    "Signals": True,
    "Corridors": True,
    "Crashes": True,
    "Original Crash Density": True,
    "Spatial Units": True,
    "Risk Segments": True,
    "Risk Corridors": True,
}

LAYER_ORDER = [
    "Roads",
    "Roads by Class/Type",
    "Signals",
    "Crashes",
    "Original Crash Density",
    "Spatial Units",
    "Corridors",
    "Risk Segments",
    "Risk Corridors",
    "Boundary",
]


def _current_layers():
    current = DEFAULT_LAYERS.copy()
    current.update(st.session_state.get("visible_layers", {}))
    return current


def is_layer_visible(layer_name, default=True):
    current = _current_layers()
    return current.get(layer_name, default)


def selected_layer_names():
    current = _current_layers()
    return [name for name in LAYER_ORDER if current.get(name, False)]


def render_layer_controls():
    """Render a compact GIS-style layer list.

    This replaces the large grouped checkbox panel and the Folium layer box.
    Users can select multiple layer names here, then every map uses that same
    app-level selection where the corresponding data exists.
    """
    st.markdown('<div class="layer-sidebar-title">Layers</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="layer-sidebar-note">Select one or more layers to display on the map.</div>',
        unsafe_allow_html=True,
    )

    current = _current_layers()
    default_selected = [name for name in LAYER_ORDER if current.get(name, False)]

    selected = st.multiselect(
        "Map layers",
        options=LAYER_ORDER,
        default=default_selected,
        label_visibility="collapsed",
        key="global_map_layer_selector",
    )

    next_state = DEFAULT_LAYERS.copy()
    for name in LAYER_ORDER:
        next_state[name] = name in selected

    st.session_state["visible_layers"] = next_state


def set_group_layer(group_name, value):
    current = _current_layers()
    current[group_name] = value
    st.session_state["visible_layers"] = current
