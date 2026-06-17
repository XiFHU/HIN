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
_real_st_folium = st_folium
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
    initial_sidebar_state="expanded"
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
        padding: 0rem 0.35rem 0rem 0.35rem !important;
        max-width: 100% !important;
        height: 100vh !important;
        overflow: hidden !important;
    }

    /* Keep Streamlit's native top-right running indicator visible. */
    [data-testid="stHeader"] {
        display: block;
        background: rgba(255, 255, 255, 0.65);
        height: 2.2rem;
    }

    [data-testid="stSidebar"] {
        min-width: 340px !important;
        overflow: visible !important;
        background: rgba(
            248,
            249,
            250,
            0.96
        );
        border-right: 1px solid #cfcfcf;
    }

    [data-testid="stSidebar"] > div:first-child {
        height: calc(100vh - 2.2rem) !important;
        max-height: calc(100vh - 2.2rem) !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;

        padding-top: 0.45rem !important;
        padding-left: 0.55rem !important;
        padding-right: 0.55rem !important;
        padding-bottom: 60vh !important;

        box-sizing: border-box !important;

        scrollbar-width: thin;
        scrollbar-color: #777 #e9ecef;
    }

    [data-testid="stSidebar"] > div:first-child::-webkit-scrollbar {
        width: 10px !important;
    }

    [data-testid="stSidebar"] > div:first-child::-webkit-scrollbar-track {
        background: #e9ecef !important;
    }

    [data-testid="stSidebar"] > div:first-child::-webkit-scrollbar-thumb {
        background: #777 !important;
        border-radius: 10px !important;
    }

    .hin-header {
        height: 34px;
        display: flex;
        align-items: center;
        gap: 10px;
        border-bottom: 1px solid #d0d0d0;
        background: white;
        padding: 0 10px;
        margin: 0;
    }

    .hin-title {
        font-size: 15px;
        font-weight: 700;
        white-space: nowrap;
        margin-right: 8px;
    }

    .workflow-label {
        font-size: 13px;
        font-weight: 700;
        margin: 0.15rem 0 0.35rem 0;
    }

    .section-title {
        font-size: 13px;
        font-weight: 700;
        margin: 0.3rem 0 0.2rem 0;
        padding-bottom: 0.1rem;
        border-bottom: 1px solid #e0e0e0;
    }

    /* Keep the Folium component at the top of the main page.
       Do not wrap it in a fixed-height HTML div because Streamlit components
       render as separate blocks and the wrapper can create a large blank gap. */
    iframe {
        border: 0 !important;
        border-radius: 0 !important;
    }

    [data-testid="stVerticalBlock"] > [style*="flex-direction: column"] {
        gap: 0.15rem !important;
    }

    h1 { font-size: 17px !important; margin: 0.2rem 0 !important; }
    h2 { font-size: 15px !important; margin: 0.2rem 0 !important; }
    h3 { font-size: 13px !important; margin: 0.15rem 0 !important; }
    h4 { font-size: 12px !important; margin: 0.15rem 0 !important; }
    p, label, span, .stMarkdown, .stCaption, div[data-testid="stWidgetLabel"] {
        font-size: 11.5px !important;
    }

    .stRadio, .stCheckbox, .stSelectbox, .stMultiSelect, .stNumberInput, .stTextInput {
        margin-bottom: 0.15rem !important;
    }

    [data-testid="stFileUploader"] {
        margin: 0.05rem 0 0.25rem 0 !important;
    }

    [data-testid="stFileUploaderDropzone"] {
        padding: 0.3rem !important;
        min-height: 45px !important;
    }

    .stButton button, .stDownloadButton button {
        font-size: 11.5px !important;
        padding: 0.16rem 0.45rem !important;
        min-height: 27px !important;
    }

    .stAlert {
        padding: 0.35rem 0.5rem !important;
        margin: 0.2rem 0 !important;
    }

    .stDataFrame,
    [data-testid="stDataFrame"] {
        width: 100% !important;
        max-width: 100% !important;

        overflow: visible !important;

        padding-bottom: 2px !important;

        scrollbar-width: thin;
        scrollbar-color: #777 #f0f0f0;
    }

    [data-testid="stDataFrame"] ::-webkit-scrollbar {
        height: 6px !important;
        width: 6px !important;
    }

    [data-testid="stDataFrame"] ::-webkit-scrollbar-track {
        background: #f0f0f0 !important;
    }

    [data-testid="stDataFrame"] ::-webkit-scrollbar-thumb {
        background: #777 !important;
        border-radius: 8px !important;
    }

    [data-testid="stDataFrame"] ::-webkit-scrollbar-thumb:hover {
        background: #555 !important;
    }

    .element-container:has([data-testid="stDataFrame"]) {
        margin-bottom: 0.45rem !important;
    }

    hr {
        margin: 0.3rem 0 !important;
    }

    div[data-testid="stExpander"] {
        margin-bottom: 0.25rem !important;
    }

    div[data-testid="stExpander"] details summary {
        padding-top: 0.22rem !important;
        padding-bottom: 0.22rem !important;
        font-size: 11.5px !important;
    }

    .layer-sidebar-title {
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }

    .layer-sidebar-note {
        font-size: 10.5px;
        color: #666;
        margin-bottom: 0.35rem;
    }

    /* Keep the top Intersection / Corridor / Segment selector available.
       This keeps the existing position, but prevents the map/component area
       from covering it after reruns. */
    section.main > div div[data-testid="stRadio"]:first-of-type {
        position: sticky !important;

        top: 2.2rem !important;

        z-index: 10000 !important;

        background: rgba(
            255,
            255,
            255,
            0.96
        ) !important;

        padding: 0.25rem 0.35rem !important;

        border-bottom: 1px solid #d9d9d9 !important;
    }

    /* Keep the map iframe below the sticky workflow selector. */
    .element-container iframe {
        max-width: 100% !important;
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
# GIS-style UI shell
# =====================================================

st.markdown(
    """
    <div class="hin-header">
        <div class="hin-title">HIN Analysis Tool</div>
    </div>
    """,
    unsafe_allow_html=True
)

# Top navigation stays compact above the map. The sidebar behaves like a GIS
# navigation/layer pane and can be collapsed by Streamlit's native sidebar icon.
selector_slot = st.container()

with selector_slot:
    spatial_unit = st.radio(
        "Spatial Unit",
        ["Intersection", "Corridor", "Segment"],
        horizontal=True,
        label_visibility="collapsed",
        key="spatial_unit_selector"
    )

# When switching workflow tabs, keep uploaded base data but clear the displayed
# map HTML so results from the previous workflow do not remain visible.
_previous_spatial_unit = st.session_state.get(
    "_active_spatial_unit"
)

if _previous_spatial_unit != spatial_unit:

    st.session_state[
        "_active_spatial_unit"
    ] = spatial_unit

    st.session_state.pop(
        "last_main_map_html",
        None
    )

    st.session_state[
        "last_map_ready"
    ] = False

    # Keep shared uploaded inputs, but clear workflow-specific result display.
    # This lets users jump between Intersection, Corridor, and Segment without
    # old result layers/tables blocking the next workflow.
    for k in [
        "spatial_units",
        "spatial_units_density_map",
        "assigned_crashes",
        "kabco_result",
        "analysis_type",
        "intersection_source",
        "segment_unit_method",
        "section7_results",
        "section7_original_density",
        "section7_crashes_for_map",
        "section7_route_col_s7"
    ]:
        st.session_state.pop(
            k,
            None
        )

    st.session_state[
        "active_map_layer"
    ] = "Roads"

# Reserve the main map area immediately below the top navigation.
# The sidebar workflow can scroll independently, but this placeholder stays
# at the top of the page and is filled after the workflow queues its latest map.
main_map_slot = st.empty()

# The sidebar workflow can queue maps many times during one rerun.
# To avoid flashing/blank Folium components, render only once at the end
# and keep the last good HTML map as a fallback.
main_map_state = {
    "fmap": None,
    "height": 820,
    "key": "main_gis_map",
    "kwargs": {},
}


def render_main_map(fmap, width=None, height=900, key=None, **kwargs):
    """Queue the latest Folium map. It is rendered once in the main pane."""
    main_map_state["fmap"] = fmap
    main_map_state["height"] = 860
    main_map_state["key"] = "main_gis_map"
    main_map_state["kwargs"] = kwargs
    return None


# Workflow code still calls st_folium(...), but this name now only queues the
# latest map. The actual display is handled once after the sidebar finishes.
st_folium = render_main_map

from ui.workflows import render_workflow

with st.sidebar:
    with st.expander("Workflow setup", expanded=True):
        render_workflow(
            spatial_unit=spatial_unit,
            st_folium=st_folium,
            workflow_context=globals().copy()
        )


def _queue_fallback_map_if_needed():
    """Queue a useful, tab-aware map if the current workflow did not queue one.

    Uploaded road data is shared across tabs, but workflow result layers are not
    mixed between tabs. This prevents an Intersection result map from remaining
    visible when the user switches to Corridor or Segment.
    """
    if main_map_state["fmap"] is not None:
        return

    selected_roads = st.session_state.get("selected_roads")
    selected_boundary = st.session_state.get("selected_boundary")

    if selected_roads is None:
        st.session_state.pop("last_main_map_html", None)
        return

    roads_class_display = st.session_state.get("roads_class_display", None) if st.session_state.get("road_class_layer_enabled", False) else None

    # Base layers persist within all workflows after FromMile/ToMile is ready.
    # Boundary is included but defaulted off inside make_map so users can turn it
    # on from the Folium LayerControl when needed.
    map_kwargs = {
        "boundary": selected_boundary,
        "roads": selected_roads,
        "roads_class": roads_class_display,
        "signals": None,
        "corridors": None,
        "spatial_units": None,
        "crashes": None,
    }

    if spatial_unit == "Intersection":
        map_kwargs["signals"] = st.session_state.get("signals_clean")
        if st.session_state.get("analysis_type") in [
            "Intersection",
            "Signalized Intersection",
            "Signalized Intersection Crashes",
        ]:
            map_kwargs["spatial_units"] = st.session_state.get("spatial_units")
            map_kwargs["crashes"] = st.session_state.get(
                "assigned_crashes",
                st.session_state.get("crashes")
            )
        else:
            map_kwargs["crashes"] = st.session_state.get("crashes")

    elif spatial_unit == "Corridor":
        map_kwargs["signals"] = st.session_state.get("signals_clean")
        map_kwargs["corridors"] = st.session_state.get("corridors")
        if st.session_state.get("analysis_type") == "Corridor":
            map_kwargs["spatial_units"] = st.session_state.get("spatial_units")
            map_kwargs["crashes"] = st.session_state.get(
                "assigned_crashes",
                st.session_state.get("crashes")
            )
        else:
            map_kwargs["crashes"] = st.session_state.get("crashes")

    elif spatial_unit == "Segment":
        # Do not show Intersection/Corridor result layers here. Segment layers
        # are queued by the Segment workflow after classification or HIN runs.
        if st.session_state.get("analysis_type") in [
            "Road Segment",
            "Uploaded Road Segment",
            "Segment",
        ]:
            map_kwargs["spatial_units"] = st.session_state.get("spatial_units")
            map_kwargs["crashes"] = st.session_state.get(
                "assigned_crashes",
                st.session_state.get("crashes")
            )
        else:
            map_kwargs["crashes"] = st.session_state.get("crashes")

    try:
        main_map_state["fmap"] = make_map(**map_kwargs)
    except Exception:
        main_map_state["fmap"] = make_map(
            boundary=selected_boundary,
            roads=selected_roads,
            roads_class=roads_class_display
        )

    main_map_state["height"] = 860
    main_map_state["key"] = "main_gis_map"
    main_map_state["kwargs"] = {}

_queue_fallback_map_if_needed()

with main_map_slot.container():
    if main_map_state["fmap"] is not None:
        try:
            with st.spinner("Rendering map layers..."):
                _real_st_folium(
                    main_map_state["fmap"],
                    width=None,
                    height=main_map_state.get("height", 860),
                    key="main_gis_map",
                    returned_objects=[],
                )
            st.session_state["last_map_ready"] = True
        except Exception as e:
            st.warning(f"Map render failed: {e}")
    elif st.session_state.get("selected_roads") is not None:
        st.info("Map status: roads are loaded. Preparing map layers...")
    else:
        st.info("Upload/select roads to begin. The map will remain here while you work in the sidebar.")
