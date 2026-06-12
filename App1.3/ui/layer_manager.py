"""Layer controls for the fixed-window HIN app."""

import streamlit as st

DEFAULT_LAYERS = {
    "Boundary": True,
    "Roads": True,
    "Signals": True,
    "Corridors": True,
    "Crashes": True,
    "Spatial Units": True,
    "Risk Segments": True,
    "Risk Corridors": True,
}


def is_layer_visible(layer_name, default=True):
    visible_layers = st.session_state.get("visible_layers", DEFAULT_LAYERS.copy())
    return visible_layers.get(layer_name, default)


def set_group_layer(group_name, value):
    visible_layers = st.session_state.get("visible_layers", DEFAULT_LAYERS.copy())
    visible_layers[group_name] = value
    st.session_state["visible_layers"] = visible_layers


def render_layer_controls():
    """Render grouped layer checkboxes in the left panel.

    These are app-level controls. Folium still has its own small layer control
    inside the map for individual road classes/corridor features.
    """
    st.markdown("### Layer Controls")

    current = st.session_state.get("visible_layers", DEFAULT_LAYERS.copy())

    with st.expander("Base Layers", expanded=True):
        current["Boundary"] = st.checkbox(
            "Boundary",
            value=current.get("Boundary", True),
            key="layer_boundary",
        )
        current["Roads"] = st.checkbox(
            "Roads",
            value=current.get("Roads", True),
            key="layer_roads",
        )

    with st.expander("Input Layers", expanded=True):
        current["Signals"] = st.checkbox(
            "Signals",
            value=current.get("Signals", True),
            key="layer_signals",
        )
        current["Crashes"] = st.checkbox(
            "Crashes",
            value=current.get("Crashes", True),
            key="layer_crashes",
        )

    with st.expander("Spatial Unit Layers", expanded=True):
        current["Corridors"] = st.checkbox(
            "Corridors - turn all on/off",
            value=current.get("Corridors", True),
            key="layer_corridors",
        )
        current["Spatial Units"] = st.checkbox(
            "Spatial Units / Crash Density",
            value=current.get("Spatial Units", True),
            key="layer_spatial_units",
        )

    with st.expander("Risk Layers", expanded=True):
        current["Risk Segments"] = st.checkbox(
            "Risk Segments",
            value=current.get("Risk Segments", True),
            key="layer_risk_segments",
        )
        current["Risk Corridors"] = st.checkbox(
            "Risk Corridors",
            value=current.get("Risk Corridors", True),
            key="layer_risk_corridors",
        )

    st.session_state["visible_layers"] = current
