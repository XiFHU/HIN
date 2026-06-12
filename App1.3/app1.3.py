import contextily as ctx
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import pandas as pd
import io
import json
import folium
import zipfile
import folium.plugins
import tempfile
import os
import streamlit as st
from streamlit_folium import st_folium
import geopandas as gpd
from shapely.ops import substring, linemerge, unary_union
from modules.crash_density import add_crash_density
import branca.colormap as cm
import numpy as np
from modules.io_utils import load_vector, load_crash_file
from modules.roads import (
    get_city_names,
    get_city_names_in_road_area,
    clip_city_roads,
    get_road_classes,
    filter_road_classes,
)
from modules.signals import (
    download_signals,
    remove_duplicate_signals,
    filter_signals_to_roads,
    assign_corridor_ids_to_signals,
    corridor_signal_summary,
)
from modules.corridors import build_corridors
from modules.crashes import crash_points
from modules.crash_classification import (
    create_intersection_units,
    create_corridor_units,
    create_road_segment_units,
    assign_crashes_to_units,
    summarize_kabco,
)
from modules.exports import (
    export_csv_bytes,
)

from modules.route_milepost import generate_from_to_mile

from modules.sliding_window import (
    run_sliding_window_risk_analysis,
    make_section7_context_map,
    gdf_to_geojson_bytes,
    df_to_csv_bytes,
    section7_excel_bytes,
    section7_clean_risk_segments,
    section7_clean_risk_corridors,
)

from ui.map_view import (
    add_map_elements,
    clean_for_map,
    export_geojson_bytes,
    filter_points_to_units,
    geojson_zip_for_layers,
    id_color,
    make_json_safe_gdf,
    make_map,
    make_map_safe_gdf,
    road_class_color,
)
from ui.layer_manager import is_layer_visible, render_layer_controls
st.set_page_config(
    page_title="HIN Analysis Tool",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"] {
        height: 100vh;
        overflow: hidden;
        font-size: 12px;
    }

    .block-container {
        padding: 0rem 0.35rem 0.25rem 0.35rem;
        max-width: 100%;
    }

    [data-testid="stHeader"] {
        display: none;
    }

    .hin-header {
        height: 38px;
        display: flex;
        align-items: center;
        gap: 10px;
        border-bottom: 1px solid #d9d9d9;
        background: white;
        padding: 0 8px;
        margin-bottom: 3px;
    }

    .hin-title {
        font-size: 16px;
        font-weight: 700;
        white-space: nowrap;
        margin-right: 8px;
    }

    .workflow-label {
        font-size: 14px;
        font-weight: 700;
        margin: 0.15rem 0 0.35rem 0;
    }

    .section-title {
        font-size: 14px;
        font-weight: 700;
        margin: 0.45rem 0 0.25rem 0;
        padding-bottom: 0.15rem;
        border-bottom: 1px solid #e0e0e0;
    }

    div[data-testid="column"]:first-child {
        max-height: calc(100vh - 48px);
        overflow-y: auto;
        padding: 0.35rem 0.45rem;
        border-right: 1px solid #d9d9d9;
        background: #f8f9fa;
    }

    div[data-testid="column"]:nth-child(2) {
        height: calc(100vh - 48px);
        max-height: calc(100vh - 48px);
        overflow: hidden;
        padding: 0.1rem 0.1rem 0 0.25rem;
    }

    h1 { font-size: 18px !important; margin: 0.25rem 0 !important; }
    h2 { font-size: 16px !important; margin: 0.25rem 0 !important; }
    h3 { font-size: 14px !important; margin: 0.2rem 0 !important; }
    h4 { font-size: 13px !important; margin: 0.2rem 0 !important; }
    p, label, span, .stMarkdown, .stCaption, div[data-testid="stWidgetLabel"] {
        font-size: 12px !important;
    }

    .stRadio, .stCheckbox, .stSelectbox, .stMultiSelect, .stNumberInput, .stTextInput {
        margin-bottom: 0.2rem !important;
    }

    [data-testid="stFileUploader"] {
        margin: 0.1rem 0 0.35rem 0 !important;
    }

    [data-testid="stFileUploaderDropzone"] {
        padding: 0.35rem !important;
        min-height: 50px !important;
    }

    .stButton button, .stDownloadButton button {
        font-size: 12px !important;
        padding: 0.2rem 0.55rem !important;
        min-height: 30px !important;
    }

    .stAlert {
        padding: 0.4rem 0.55rem !important;
        margin: 0.25rem 0 !important;
    }

    .stDataFrame {
        max-height: 220px;
        overflow: auto;
    }

    hr {
        margin: 0.35rem 0 !important;
    }

    iframe {
        border-radius: 6px;
        height: calc(100vh - 52px) !important;
        min-height: calc(100vh - 52px) !important;
    }

    [title="streamlit_folium.st_folium"] {
        height: calc(100vh - 52px) !important;
        min-height: calc(100vh - 52px) !important;
    }

    .folium-map {
        height: calc(100vh - 52px) !important;
    }

    /* Keep workflow and map as two independent panes. Only the left pane scrolls. */
    section.main > div {
        overflow: hidden !important;
    }

    .map-sticky-panel {
        position: sticky;
        top: 42px;
        height: calc(100vh - 46px);
        min-height: calc(100vh - 46px);
        overflow: hidden;
    }

    .map-sticky-panel iframe,
    .map-sticky-panel [title="streamlit_folium.st_folium"] {
        height: calc(100vh - 54px) !important;
        min-height: calc(100vh - 54px) !important;
    }

    div[data-testid="stExpander"] {
        margin-bottom: 0.28rem !important;
    }

    div[data-testid="stExpander"] details summary {
        padding-top: 0.25rem !important;
        padding-bottom: 0.25rem !important;
        font-size: 12px !important;
    }

    </style>
    """,
    unsafe_allow_html=True
)

def create_static_map_pdf(
    boundary=None,
    roads=None,
    signals=None,
    spatial_units=None,
    crashes=None,
    title="Crash Assignment Map"
):

    pdf_buffer = io.BytesIO()

    fig, ax = plt.subplots(
        figsize=(
            11,
            8.5
        )
    )

    legend_items = []

    if boundary is not None and not boundary.empty:
        boundary.to_crs(epsg=3857).boundary.plot(
            ax=ax,
            linewidth=1,
            color="black"
        )

        legend_items.append(
            Line2D(
                [0],
                [0],
                color="black",
                linewidth=1,
                label="Boundary"
            )
        )

    if roads is not None and not roads.empty:
        roads.to_crs(epsg=3857).plot(
            ax=ax,
            linewidth=0.5,
            color="gray"
        )

        legend_items.append(
            Line2D(
                [0],
                [0],
                color="gray",
                linewidth=1,
                label="Roads"
            )
        )

    if spatial_units is not None and not spatial_units.empty and is_layer_visible("Spatial Units"):

        spatial_units_plot = spatial_units.to_crs(
            epsg=3857
        ).copy()

        spatial_units_plot["CrashDensity"] = pd.to_numeric(
            spatial_units_plot["CrashDensity"],
            errors="coerce"
        ).fillna(0)

        spatial_units_plot.plot(
            ax=ax,
            column="CrashDensity",
            cmap="RdYlGn_r",
            linewidth=8,
            alpha=1.0,
            legend=True,
            legend_kwds={
                "label": "Crash Density",
                "shrink": 0.6
            }
        )
        try:

            import contextily as ctx

            ctx.add_basemap(
                ax,
                source=ctx.providers.OpenStreetMap.Mapnik,
                crs="EPSG:3857",
                zoom=13
            )

        except Exception as e:

            print(
                f"Could not add OSM basemap: {e}"
            )
    if crashes is not None and not crashes.empty:
        crashes.to_crs(epsg=3857).plot(
            ax=ax,
            markersize=20,
            color="black",
            alpha=0.8
        )

        legend_items.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="black",
                linestyle="None",
                markersize=5,
                label="Assigned Crashes"
            )
        )

    if signals is not None and not signals.empty:
        signals.to_crs(epsg=3857).plot(
            ax=ax,
            markersize=80,
            color="red",
            marker="^"
        )

        legend_items.append(
            Line2D(
                [0],
                [0],
                marker="^",
                color="red",
                linestyle="None",
                markersize=7,
                label="Signals"
            )
        )

    ax.set_title(
        title,
        fontsize=16
    )

    ax.set_axis_off()

    if legend_items:
        ax.legend(
            handles=legend_items,
            loc="lower left"
        )

    # North arrow
    ax.annotate(
        "N",
        xy=(
            0.95,
            0.88
        ),
        xytext=(
            0.95,
            0.78
        ),
        arrowprops=dict(
            facecolor="black",
            width=4,
            headwidth=12
        ),
        ha="center",
        va="center",
        fontsize=14,
        xycoords=ax.transAxes
    )

    # Scale bar: 1 mile
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()

    scale_m = 1609.344
    scale_x = x_min + 0.08 * (x_max - x_min)
    scale_y = y_min + 0.08 * (y_max - y_min)

    ax.plot(
        [
            scale_x,
            scale_x + scale_m
        ],
        [
            scale_y,
            scale_y
        ],
        color="black",
        linewidth=3
    )

    ax.text(
        scale_x + scale_m / 2,
        scale_y + 0.02 * (y_max - y_min),
        "1 mile",
        ha="center",
        fontsize=10
    )

    plt.tight_layout()

    fig.savefig(
        pdf_buffer,
        format="pdf",
        bbox_inches="tight"
    )

    plt.close(fig)

    pdf_buffer.seek(0)

    return pdf_buffer.getvalue()

def load_uploaded_shapefile_components(uploaded_files):
    with tempfile.TemporaryDirectory() as tmpdir:

        shp_path = None

        for uploaded_file in uploaded_files:

            file_path = os.path.join(
                tmpdir,
                uploaded_file.name
            )

            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            if uploaded_file.name.lower().endswith(".zip"):

                import zipfile

                with zipfile.ZipFile(file_path, "r") as z:
                    z.extractall(tmpdir)

            elif uploaded_file.name.lower().endswith(".shp"):

                shp_path = file_path

        if shp_path is None:

            for root, dirs, files in os.walk(tmpdir):
                for file in files:
                    if file.lower().endswith(".shp"):
                        shp_path = os.path.join(root, file)
                        break

                if shp_path is not None:
                    break

        if shp_path is None:
            raise ValueError(
                "No .shp file found. Upload a ZIP containing .shp, .dbf, .shx, .prj, or upload components together."
            )

        gdf = gpd.read_file(shp_path)

    return gdf


def export_shapefile_zip_bytes(gdf, layer_name):
    """Export a GeoDataFrame as a zipped ESRI Shapefile."""
    zip_buffer = io.BytesIO()

    with tempfile.TemporaryDirectory() as tmpdir:
        shp_dir = os.path.join(tmpdir, layer_name)
        os.makedirs(shp_dir, exist_ok=True)

        shp_path = os.path.join(shp_dir, f"{layer_name}.shp")
        gdf.to_file(shp_path, driver="ESRI Shapefile")

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(shp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    zf.write(file_path, arcname=file)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()



def find_filter_columns(df):
    keywords = [
        "year",
        "type",
        "crash_type",
        "collision",
        "manner",
        "severity",
        "kabco"
    ]

    cols = []

    for c in df.columns:
        name = (
            str(c)
            .lower()
            .replace(" ", "_")
        )

        if any(k in name for k in keywords):
            cols.append(c)

    return cols


# =====================================================
# Fixed-window GIS-style UI shell
# =====================================================

st.markdown(
    """
    <div class="hin-header">
        <div class="hin-title">HIN Analysis Tool</div>
    </div>
    """,
    unsafe_allow_html=True
)

nav_col, help_col = st.columns([0.74, 0.26])

with nav_col:
    spatial_unit = st.radio(
        "Spatial Unit",
        ["Intersection", "Corridor", "Segment"],
        horizontal=True,
        label_visibility="collapsed",
        key="spatial_unit_selector"
    )

with help_col:
    st.caption("Expand one workflow section at a time. The map stays fixed on the right.")

left_panel, map_panel = st.columns([0.28, 0.72], gap="small")

_real_st_folium = st_folium

# During one Streamlit rerun, several workflow steps may create maps
# (roads, signals, crashes, results). Do NOT render each one immediately.
# Queue the latest map and render only once after the left workflow finishes.
main_map_state = {
    "fmap": None,
    "height": 900,
    "key": None,
    "kwargs": {},
}

def render_main_map(fmap, width=None, height=900, key=None, **kwargs):
    """Queue the latest Folium map. It is rendered once in the right map panel."""
    main_map_state["fmap"] = fmap
    main_map_state["height"] = 900
    main_map_state["key"] = key
    main_map_state["kwargs"] = kwargs
    return None

st_folium = render_main_map



from ui.workflows import render_workflow

with left_panel:
    render_workflow(spatial_unit=spatial_unit, st_folium=st_folium, workflow_context=globals().copy())

def _queue_fallback_map_if_needed():
    """Always keep a useful map visible on the right pane.

    Some workflow sections are folded by default. If no step queues a new map
    during the current rerun, use the latest layers already stored in
    session_state so the map area does not go blank after actions such as
    Generate FromMile/ToMile.
    """
    if main_map_state["fmap"] is not None:
        return

    selected_roads = st.session_state.get("selected_roads")
    selected_boundary = st.session_state.get("selected_boundary")

    if selected_roads is None:
        return

    roads_for_map = st.session_state.get("roads_map_display", selected_roads)
    signals = st.session_state.get("signals_clean")
    corridors = st.session_state.get("corridors")
    spatial_units = st.session_state.get("spatial_units")
    crashes = st.session_state.get("assigned_crashes", st.session_state.get("crashes"))

    try:
        main_map_state["fmap"] = make_map(
            boundary=selected_boundary,
            roads=roads_for_map,
            signals=signals,
            corridors=corridors,
            spatial_units=spatial_units,
            crashes=crashes
        )
        main_map_state["height"] = 900
        main_map_state["key"] = "fallback_main_map"
        main_map_state["kwargs"] = {}
    except Exception:
        # Keep the app usable even if a partially generated layer is invalid.
        main_map_state["fmap"] = make_map(
            boundary=selected_boundary,
            roads=roads_for_map
        )
        main_map_state["height"] = 900
        main_map_state["key"] = "fallback_roads_map"
        main_map_state["kwargs"] = {}


_queue_fallback_map_if_needed()

with map_panel:
    st.markdown('<div class="map-sticky-panel">', unsafe_allow_html=True)

    if main_map_state["fmap"] is not None:
        _real_st_folium(
            main_map_state["fmap"],
            width=None,
            height=main_map_state["height"],
            key=main_map_state["key"],
            **main_map_state["kwargs"]
        )
    else:
        st.info(
            "Upload/select roads to begin. The latest generated layer map will appear here."
        )

    st.markdown('</div>', unsafe_allow_html=True)
