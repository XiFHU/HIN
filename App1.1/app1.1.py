import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import pandas as pd
import io
import zipfile
import folium.plugins
import tempfile
import os
import streamlit as st
from streamlit_folium import st_folium
import geopandas as gpd
import folium
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

st.set_page_config(
    page_title="Corridor Crash Tool",
    layout="wide"
)

st.title("Local Corridor Crash Analysis Tool")

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

    if spatial_units is not None and not spatial_units.empty:

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
            linewidth=1.2,
            edgecolor="black",
            alpha=0.65,
            legend=True,
            legend_kwds={
                "label": "Crash Density",
                "shrink": 0.6
            }
        )

    if crashes is not None and not crashes.empty:
        crashes.to_crs(epsg=3857).plot(
            ax=ax,
            markersize=8,
            color="black",
            alpha=0.7
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
            markersize=30,
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

def add_map_elements(fmap):

    folium.plugins.MeasureControl(
        position="bottomleft",
        primary_length_unit="miles",
        secondary_length_unit="feet"
    ).add_to(fmap)

    north_arrow_html = """
    <div style="
        position: fixed;
        top: 80px;
        right: 30px;
        z-index: 9999;
        background: white;
        padding: 8px;
        border: 2px solid black;
        font-size: 22px;
        font-weight: bold;
        text-align: center;
    ">
        ↑<br>N
    </div>
    """

    fmap.get_root().html.add_child(
        folium.Element(north_arrow_html)
    )

    return fmap

def make_json_safe_gdf(gdf):
    if gdf is None:
        return None

    gdf = gdf.copy()

    for col in gdf.columns:
        if col == "geometry":
            continue

        gdf[col] = gdf[col].apply(
            lambda x: None if x is None or str(x) in ["nan", "NaT"] else str(x)
        )

    return gdf

def make_map_safe_gdf(
    gdf,
    numeric_cols=None
):
    if gdf is None:
        return None

    if numeric_cols is None:
        numeric_cols = []

    gdf = gdf.copy()

    for col in gdf.columns:
        if col == "geometry":
            continue

        if col in numeric_cols:
            gdf[col] = pd.to_numeric(
                gdf[col],
                errors="coerce"
            ).fillna(0)
        else:
            gdf[col] = gdf[col].apply(
                lambda x: None
                if x is None or str(x) in ["nan", "NaT"]
                else str(x)
            )

    return gdf

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

def road_class_color(road_class):

    colors = {
        "Interstate": "red",
        "U.S.": "orange",
        "State Recognized": "blue",
        "County": "green",
        "Common Name": "purple",
        "Other": "gray",
        "Unknown": "black",
    }

    return colors.get(
        road_class,
        "gray"
    )
def export_geojson_bytes(gdf):
    return gdf.to_json().encode("utf-8")

def id_color(value):
    try:
        idx = int(str(value).split("_")[-1])
    except Exception:
        idx = abs(hash(str(value)))

    colors = [
        "red",
        "blue",
        "green",
        "purple",
        "orange",
        "darkred",
        "cadetblue",
        "darkgreen",
        "darkblue",
        "darkpurple",
        "gray",
        "black",
    ]

    return colors[idx % len(colors)]


def clean_for_map(gdf):
    if gdf is None or gdf.empty:
        return None

    gdf = gdf.copy()
    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    if gdf.empty:
        return None

    gdf = gdf.to_crs(4326)

    gdf["geometry"] = gdf.geometry.make_valid()
    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    gdf = gdf[
        gdf.geometry.geom_type.isin(
            [
                "Point",
                "MultiPoint",
                "LineString",
                "MultiLineString",
                "Polygon",
                "MultiPolygon",
            ]
        )
    ].copy()

    if gdf.empty:
        return None

    return gdf

def filter_points_to_units(points, units, buffer_m=20):
    if points is None or points.empty:
        return points

    if units is None or units.empty:
        return points.iloc[0:0].copy()

    points_proj = points.to_crs(epsg=3857).copy()
    units_proj = units.to_crs(epsg=3857).copy()

    units_buffer = units_proj.copy()
    units_buffer["geometry"] = units_buffer.geometry.buffer(buffer_m)

    joined = gpd.sjoin(
        points_proj,
        units_buffer[["geometry"]],
        how="inner",
        predicate="intersects"
    )

    filtered = points_proj.loc[
        points_proj.index.isin(joined.index)
    ].copy()

    return filtered.to_crs(points.crs)


def geojson_zip_for_layers(layer_dict):
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for layer_name, gdf in layer_dict.items():
            if gdf is not None and not gdf.empty:

                safe_gdf = make_json_safe_gdf(
                    gdf.to_crs(4326)
                )

                geojson_text = safe_gdf.to_json(
                    na="drop"
                )

                zf.writestr(
                    f"{layer_name}.geojson",
                    geojson_text
                )

    zip_buffer.seek(0)
    return zip_buffer.getvalue()

def make_map(
    boundary=None,
    roads=None,
    signals=None,
    corridors=None,
    spatial_units=None,
    crashes=None,
    density_cmap=None
):
    center_source = None

    for gdf in [
        spatial_units,
        corridors,
        crashes,
        signals,
        roads,
        boundary
    ]:
        clean_gdf = clean_for_map(gdf)

        if clean_gdf is not None:
            center_source = clean_gdf
            break

    if center_source is not None:
        center_geom = center_source.geometry.union_all().centroid
        location = [center_geom.y, center_geom.x]
        zoom_start = 12
    else:
        location = [39.7, -104.9]
        zoom_start = 10

    fmap = folium.Map(
        location=location,
        zoom_start=zoom_start,
        tiles="OpenStreetMap"
    )

    boundary = clean_for_map(boundary)
    boundary = make_json_safe_gdf(boundary)

    if boundary is not None:
        folium.GeoJson(
            boundary,
            name="Selected Boundary",
            style_function=lambda feature: {
                "color": "black",
                "weight": 2,
                "fillOpacity": 0.02,
            },
        ).add_to(fmap)

    roads = clean_for_map(roads)
    roads = make_json_safe_gdf(roads)

    if roads is not None:
        road_lines = roads[
            roads.geometry.geom_type.isin(
                ["LineString", "MultiLineString"]
            )
        ].copy()

        if not road_lines.empty:

            if "RoadClass" in road_lines.columns:
                groups = road_lines.groupby("RoadClass")
            else:
                groups = [("Unknown", road_lines)]

            for road_class, sub in groups:

                sub = make_json_safe_gdf(sub)

                folium.GeoJson(
                    sub,
                    name=f"{road_class}",
                    style_function=lambda feature, road_class=road_class: {
                        "color": road_class_color(road_class),
                        "weight": 3,
                        "opacity": 0.9,
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=[
                            c for c in [
                                "FULLNAME",
                                "RouteName_Calc",
                                "FromMile",
                                "ToMile",
                                "RoadClass",
                                "RoadType"
                            ]
                            if c in sub.columns
                        ]
                    )
                ).add_to(fmap)

    corridors = clean_for_map(corridors)
    corridors = make_json_safe_gdf(corridors)

    if corridors is not None:
        id_field = None

        if "CorridorID" in corridors.columns:
            id_field = "CorridorID"
        elif "corridor_id" in corridors.columns:
            id_field = "corridor_id"

        if id_field is not None:
            for corridor_id, sub in corridors.groupby(id_field):
                color = id_color(corridor_id)

                sub = make_json_safe_gdf(sub)

                tooltip_fields = [
                    c for c in [
                        id_field,
                        "Route",
                        "SignalCnt",
                        "CrashCount"
                    ]
                    if c in sub.columns
                ]

                folium.GeoJson(
                    sub,
                    name=f"Corridor {corridor_id}",
                    style_function=lambda feature, color=color: {
                        "color": color,
                        "fillColor": color,
                        "weight": 3,
                        "fillOpacity": 0.25,
                        "opacity": 0.9,
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=tooltip_fields
                    ) if tooltip_fields else None,
                ).add_to(fmap)

        else:
            folium.GeoJson(
                corridors,
                name="Corridors",
                style_function=lambda feature: {
                    "color": "purple",
                    "fillColor": "purple",
                    "weight": 3,
                    "fillOpacity": 0.25,
                },
            ).add_to(fmap)

    spatial_units = clean_for_map(spatial_units)

    if spatial_units is not None and not spatial_units.empty:

        spatial_units_plot = spatial_units.to_crs(
            epsg=4326
        ).copy()

        spatial_units_plot = make_map_safe_gdf(
            spatial_units_plot,
            numeric_cols=[
                "CrashDensity",
                "CrashCount",
                "Length_Miles",
                "Area_SqMi"
            ]
        )

        spatial_units_group = folium.FeatureGroup(
            name="Spatial Units - Crash Density",
            show=True
        )

        def style_spatial_unit(feature):

            density = feature["properties"].get(
                "CrashDensity",
                0
            )

            try:

                density = float(
                    density
                )

            except Exception:

                density = 0.0

            if density_cmap is not None:

                color = density_cmap(
                    density
                )

            else:

                color = "purple"

            return {
                "color": color,
                "fillColor": color,
                "weight": 4,
                "fillOpacity": 0.55,
                "opacity": 0.9,
            }

        tooltip_fields = [
            c for c in [
                "UnitID",
                "UnitType",
                "CrashCount",
                "CrashDensity",
                "Length_Miles",
                "Area_SqMi",
                "IntersectionID",
                "SegmentID",
                "CorridorID",
                "Route",
                "FULLNAME",
                "RouteName_Calc",
                "RoadName1",
                "RoadName2"
            ]
            if c in spatial_units_plot.columns
        ]

        folium.GeoJson(
            spatial_units_plot,
            name="Spatial Units - Crash Density",
            style_function=style_spatial_unit,
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_fields,
                localize=True
            ) if tooltip_fields else None,
        ).add_to(spatial_units_group)

        spatial_units_group.add_to(fmap)
        
    signals = clean_for_map(signals)
    signals = make_json_safe_gdf(signals)

    if signals is not None:
        signal_group = folium.FeatureGroup(
            name="Signals"
        )

        for _, row in signals.iterrows():
            geom = row.geometry

            if geom.geom_type == "Point":
                popup_text = ""

                if "SignalID" in row.index:
                    popup_text += f"SignalID: {row['SignalID']}<br>"

                if "City" in row.index:
                    popup_text += f"City: {row['City']}<br>"

                folium.Marker(
                    location=[
                        geom.y,
                        geom.x
                    ],
                    icon=folium.DivIcon(
                        html="""
                        <div style="font-size:18px;">🚦</div>
                        """
                    ),
                    popup=popup_text,
                ).add_to(signal_group)

        signal_group.add_to(fmap)

    crashes = clean_for_map(crashes)
    crashes = make_json_safe_gdf(crashes)

    if crashes is not None:
        crash_group = folium.FeatureGroup(
            name="Crashes"
        )

        for _, row in crashes.iterrows():
            geom = row.geometry

            if geom.geom_type == "Point":
                popup_text = ""

                if "SourceCrashID" in row.index:
                    popup_text += (
                        f"Case ID: "
                        f"{row['SourceCrashID']}<br>"
                    )

                if "CrashID" in row.index:
                    popup_text += (
                        f"App ID: "
                        f"{row['CrashID']}<br>"
                    )

                if "UnitID" in row.index:
                    popup_text += (
                        f"UnitID: "
                        f"{row['UnitID']}<br>"
                    )

                folium.CircleMarker(
                    location=[
                        geom.y,
                        geom.x
                    ],
                    radius=4,
                    color="black",
                    weight=1,
                    fill=True,
                    fill_opacity=0.8,
                    popup=popup_text,
                ).add_to(crash_group)

        crash_group.add_to(fmap)

    folium.LayerControl(
        collapsed=False
    ).add_to(fmap)

    return fmap

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

# -----------------------------
# 1. Upload roads
# -----------------------------

st.header("1. Upload Roads")

road_source = st.radio(
    "Choose road source",
    [
        "Use TIGER roads + PLACE boundary",
        "Upload custom road network"
    ],
    horizontal=True
)

roads = None
places = None
selected_roads = None
selected_boundary = None


# =====================================================
# Option A: Original TIGER workflow
# =====================================================
if road_source == "Use TIGER roads + PLACE boundary":

    st.subheader("Upload TIGER files")

    col1, col2 = st.columns(2)

    with col1:
        roads_file = st.file_uploader(
            "Upload county TIGER roads ZIP",
            type=["zip", "gpkg", "geojson", "json"],
            key="tiger_roads_file"
        )

    with col2:
        places_file = st.file_uploader(
            "Upload state PLACE ZIP",
            type=["zip", "gpkg", "geojson", "json"],
            key="places_file"
        )

    if roads_file and places_file:

        roads = load_vector(roads_file).to_crs(4326)
        places = load_vector(places_file).to_crs(4326)

        st.success("TIGER files loaded.")

        use_all_roads = st.checkbox(
            "Use all roads without city clipping"
        )

        if not use_all_roads:

            city_names = get_city_names_in_road_area(
                places,
                roads
            )

            city_name = st.selectbox(
                "Select city",
                city_names
            )
            
            area_name = city_name
            st.session_state["area_name"] = area_name
            
            selected_boundary = places[
                places["NAME"] == city_name
            ].copy()

            city_roads = clip_city_roads(
                roads,
                places,
                city_name
            )

        else:

            city_name = "All Roads"
            area_name = city_name
            st.session_state["area_name"] = area_name

            city_roads = roads.copy()

            selected_boundary = gpd.GeoDataFrame(
                geometry=[
                    roads.geometry.union_all().convex_hull
                ],
                crs=roads.crs
            )

        road_classes = get_road_classes(city_roads)

        selected_classes = st.multiselect(
            "Road class filter based on RTTYP",
            road_classes,
            default=road_classes
        )

        selected_roads = filter_road_classes(
            city_roads,
            selected_classes
        )

        selected_roads = selected_roads.copy()

        # TIGER default route/segment fields
        route_col = "FULLNAME"
        segment_id_col = "LINEARID" if "LINEARID" in selected_roads.columns else selected_roads.columns[0]

        st.session_state["route_col"] = route_col
        st.session_state["segment_id_col"] = segment_id_col


# =====================================================
# Option B: Custom uploaded road network
# =====================================================

else:

    st.subheader("Upload custom road network")

    st.info(
        "Upload shapefile components together "
        "(.shp, .dbf, .shx, .prj)."
    )

    custom_road_files = st.file_uploader(
        "Upload road shapefile ZIP or components",
        type=[
            "zip",
            "shp",
            "dbf",
            "shx",
            "prj",
            "cpg"
        ],
        accept_multiple_files=True,
        key="custom_road_files"
    )

    if custom_road_files:

        try:

            roads = load_uploaded_shapefile_components(
                custom_road_files
            )

        except Exception:

            st.error(
                "Unable to read shapefile. "
                "Please upload .shp, .dbf, .shx, and .prj together."
            )

            st.stop()

        if roads.crs is None:

            st.error(
                "Uploaded road file has no CRS. "
                "Please define CRS first."
            )

            st.stop()

        roads = roads.to_crs(4326)

        st.success(
            "Custom road network loaded."
        )

        area_name = st.text_input(
            "Enter study area name",
            value="Custom Road Network"
        )

        st.session_state["area_name"] = area_name

        route_col = st.selectbox(
            "Select route name column",
            roads.columns,
            key="custom_route_col"
        )

        segment_id_col = st.selectbox(
            "Select unique segment ID column",
            roads.columns,
            key="custom_segment_id_col"
        )

        direction_method = st.radio(
            "Route direction method for FromMile / ToMile",
            [
                "Auto Detect",
                "East-West",
                "North-South"
            ],
            horizontal=True,
            index=0
        )

        if st.button("Generate FromMile and ToMile"):

            selected_roads = generate_from_to_mile(
                roads=roads,
                route_col=route_col,
                segment_id_col=segment_id_col,
                direction_method=direction_method,
                start_mile=0.0
            )

            selected_roads = selected_roads.to_crs(4326)

            selected_boundary = gpd.GeoDataFrame(
                geometry=[
                    selected_roads.geometry.union_all().convex_hull
                ],
                crs=selected_roads.crs
            )

            st.session_state["selected_roads"] = selected_roads
            st.session_state["selected_boundary"] = selected_boundary
            st.session_state["route_col"] = route_col
            st.session_state["segment_id_col"] = segment_id_col

            st.success("FromMile and ToMile generated.")

        else:
            st.info("Select fields, then click Generate FromMile and ToMile.")


# ADD THIS PART
if selected_roads is None and "selected_roads" in st.session_state:
    selected_roads = st.session_state["selected_roads"]

if selected_boundary is None and "selected_boundary" in st.session_state:
    selected_boundary = st.session_state["selected_boundary"]


# =====================================================
# Shared road setup after either TIGER or custom upload
# =====================================================

if selected_roads is None and "selected_roads" in st.session_state:
    selected_roads = st.session_state["selected_roads"]

if selected_boundary is None and "selected_boundary" in st.session_state:
    selected_boundary = st.session_state["selected_boundary"]


if selected_roads is not None:

    selected_roads = selected_roads.copy()

    if "RoadClass" in selected_roads.columns:
        selected_roads["RoadClass"] = selected_roads["RoadClass"].fillna("Unknown")

    if "RoadType" in selected_roads.columns:
        selected_roads["RoadType"] = selected_roads["RoadType"].fillna("Unknown")

    st.session_state["selected_boundary"] = selected_boundary
    st.session_state["selected_roads"] = selected_roads

    col_reset1, col_reset2 = st.columns(2)

    with col_reset1:
        if st.button("Reset analysis results"):

            for k in [
                "signals_clean",
                "signals_with_corridor",
                "corridor_signal_summary",
                "corridors",
                "crashes",
                "spatial_units",
                "assigned_crashes",
                "kabco_result",
                "analysis_type",
                "classified",
                "unit_col"
            ]:
                st.session_state.pop(k, None)

            st.rerun()

    with col_reset2:
        if st.button("Reset roads and start over"):

            for k in [
                "selected_roads",
                "selected_boundary",
                "route_col",
                "segment_id_col",
                "signals_clean",
                "signals_with_corridor",
                "corridor_signal_summary",
                "corridors",
                "crashes",
                "spatial_units",
                "assigned_crashes",
                "kabco_result",
                "analysis_type",
                "classified",
                "unit_col"
            ]:
                st.session_state.pop(k, None)

            st.rerun()

    st.write(f"Selected roads: {len(selected_roads)}")

    raw_road_table_cols = [
        st.session_state.get("route_col"),
        st.session_state.get("segment_id_col"),
        "FULLNAME",
        "RouteName_Calc",
        "RouteOrder_Calc",
        "RouteAxis_Calc",
        "FromMile",
        "ToMile",
        "SegmentLength_Mile",
        "RoadClass",
        "RoadType",
        "RTTYP",
        "MTFCC"
    ]

    road_table_cols = []

    for c in raw_road_table_cols:
        if c is not None and c in selected_roads.columns and c not in road_table_cols:
            road_table_cols.append(c)

    with st.expander("Selected road attributes", expanded=False):

        if road_table_cols:
            st.dataframe(
                selected_roads[road_table_cols].drop_duplicates(),
                width="stretch"
            )
        else:
            st.info("No displayable road attribute columns found.")

    csv = selected_roads.drop(columns="geometry").to_csv(index=False)

    st.download_button(
        "Download selected roads attribute table",
        data=csv,
        file_name="selected_roads_attributes.csv",
        mime="text/csv"
    )

    fmap = make_map(
        boundary=selected_boundary,
        roads=selected_roads
    )

    st_folium(
        fmap,
        width=1200,
        height=600,
        key="road_map"
    )
# -----------------------------
# 2. Generate OSM signals
# -----------------------------

st.header("2. Generate OSM traffic signals")

signals_clean = st.session_state.get(
    "signals_clean",
    None
)

if selected_boundary is not None:

    signal_distance = st.number_input(
        "Duplicate signal distance (meters)",
        min_value=10,
        max_value=100,
        value=45,
        step=5
    )

    road_snap_distance = st.number_input(
        "Maximum distance from road (feet)",
        min_value=25,
        max_value=500,
        value=150,
        step=25
    )

    if st.button("Generate Signals"):

        with st.spinner(
            "Downloading OSM traffic signals and removing duplicates..."
        ):

            signals = download_signals(
                selected_boundary
            )

            signals_clean = remove_duplicate_signals(
                signals,
                distance_m=signal_distance
            )

            signals_clean = filter_signals_to_roads(
                signals_clean,
                selected_roads,
                max_distance_ft=road_snap_distance
            )

            signals_clean = signals_clean.reset_index(
                drop=True
            )

            signals_clean["SignalID"] = (
                signals_clean.index + 1
            )

            signals_clean["City"] = (
                st.session_state.get(
                    "area_name",
                    "Study Area"
                )
            )

            st.session_state[
                "signals_clean"
            ] = signals_clean

        st.success(
            f"Signals generated: {len(signals_clean)}"
        )
if signals_clean is not None:

    st.subheader("Cleaned Signal Table")

    signals_table = signals_clean.copy()

    if "SignalID" not in signals_table.columns:
        signals_table["SignalID"] = (
            signals_table.index + 1
        )

    if "City" not in signals_table.columns:
        signals_table["City"] = city_name

    signals_table["Latitude"] = (
        signals_table.geometry.y
    )

    signals_table["Longitude"] = (
        signals_table.geometry.x
    )

    signals_table = signals_table[
        [
            "SignalID",
            "City",
            "Latitude",
            "Longitude"
        ]
    ]

    st.dataframe(
        signals_table,
        width="stretch"
    )

    st.download_button(
        "Download Cleaned Signals CSV",
        signals_table.to_csv(index=False),
        file_name="cleaned_signals.csv",
        mime="text/csv"
    )

    signal_layers = [
        (
            selected_boundary,
            "Selected Boundary"
        ),
        (
            selected_roads,
            "Selected Roads"
        ),
        (
            signals_clean,
            "Cleaned Signals"
        )
    ]

    fmap = make_map(
        boundary=selected_boundary,
        roads=selected_roads,
        signals=signals_clean
    )

    st_folium(
        fmap,
        width=1200,
        height=600,
        key="signal_map"
    )
# -----------------------------
# 3. Advanced: Build corridors
# -----------------------------

st.header("3. Advanced: Build corridors")

area_name = st.session_state.get(
    "area_name",
    "Study Area"
)

corridors = st.session_state.get(
    "corridors",
    None
)

signals_with_corridor = st.session_state.get(
    "signals_with_corridor",
    None
)

corridor_summary = st.session_state.get(
    "corridor_signal_summary",
    None
)

if selected_roads is not None and signals_clean is not None:

    build_corr = st.checkbox(
        "Build corridors from selected signals and selected roads"
    )

    min_signals_for_corridor = st.number_input(
        "Minimum signals required to create a corridor",
        min_value=1,
        max_value=20,
        value=3,
        step=1
    )

    nearest_road_distance_m = st.number_input(
        "Maximum signal distance from named road, meters",
        min_value=10,
        max_value=200,
        value=50,
        step=10
    )

    corridor_width_m = st.number_input(
        "Corridor width, meters",
        min_value=5,
        max_value=100,
        value=20,
        step=5
    )

    corridor_search_buffer_m = st.number_input(
        "Corridor search buffer around signals, meters",
        min_value=25,
        max_value=500,
        value=150,
        step=25
    )

    if build_corr and st.button("Build Corridors"):

        with st.spinner(
            "Assigning CorridorID and building corridor polygons..."
        ):

            signals_with_corridor = assign_corridor_ids_to_signals(
                signals_clean,
                selected_roads,
                city_name=area_name,
                county_name="",
                min_signals=min_signals_for_corridor,
                max_distance_m=nearest_road_distance_m
            )

            corridor_summary = corridor_signal_summary(
                signals_with_corridor
            )

            corridors = build_corridors(
                selected_roads,
                signals_with_corridor,
                corridor_width_m=corridor_width_m,
                corridor_search_buffer_m=corridor_search_buffer_m,
                min_signals=min_signals_for_corridor,
                city_name=area_name,
                route_col=st.session_state.get(
                    "route_col",
                    "FULLNAME"
                )
            )
            st.session_state[
                "signals_with_corridor"
            ] = signals_with_corridor

            st.session_state[
                "corridor_signal_summary"
            ] = corridor_summary

            st.session_state[
                "corridors"
            ] = corridors

        st.success(
            f"Corridors built: {len(corridors)}"
        )

if signals_with_corridor is not None:

    st.subheader("Signals With CorridorID")

    signal_corridor_table = signals_with_corridor.copy()

    if "SignalID" not in signal_corridor_table.columns:
        signal_corridor_table["SignalID"] = (
            signal_corridor_table.index + 1
        )

    if "City" not in signal_corridor_table.columns:
        signal_corridor_table["City"] = area_name

    signal_corridor_table["Latitude"] = (
        signal_corridor_table.geometry.y
    )

    signal_corridor_table["Longitude"] = (
        signal_corridor_table.geometry.x
    )

    display_cols = [
        c for c in [
            "SignalID",
            "City",
            "CorridorID",
            "Route",
            "Latitude",
            "Longitude"
        ]
        if c in signal_corridor_table.columns
    ]

    signal_corridor_table = signal_corridor_table[
        display_cols
    ]

    st.dataframe(
        signal_corridor_table,
        width="stretch"
    )

    st.download_button(
        "Download Signals With CorridorID CSV",
        export_csv_bytes(signal_corridor_table),
        file_name="signals_with_corridor_id.csv",
        mime="text/csv",
        key="download_signals_with_corridor_csv"
    )

if corridor_summary is not None:

    st.subheader("Corridor Signal Summary")

    st.dataframe(
        corridor_summary,
        width="stretch"
    )

    st.download_button(
        "Download Corridor Summary CSV",
        export_csv_bytes(corridor_summary),
        file_name="corridor_summary.csv",
        mime="text/csv",
        key="download_corridor_summary_csv"
    )

if corridors is not None:

    st.subheader("Corridor Map")

    try:

        fmap = make_map(
            boundary=selected_boundary,
            roads=selected_roads,
            signals=signals_with_corridor,
            corridors=corridors
        )

        st_folium(
            fmap,
            width=1200,
            height=600,
            key="corridor_map"
        )

    except Exception as e:

        st.error(
            f"Could not draw corridor map: {e}"
        )

    st.subheader("Download Corridor Files")

    if st.button(
        "Prepare Corridor Shapefile ZIP",
        key="prepare_corridor_shp"
    ):

        try:

            corridor_shp_bytes = (
                export_shapefile_zip_bytes(
                    corridors,
                    "corridors"
                )
            )

            st.session_state[
                "corridor_shp_bytes"
            ] = corridor_shp_bytes

            st.success(
                "Corridor shapefile ZIP ready."
            )

        except Exception as e:

            st.error(
                f"Could not create Corridor Shapefile ZIP: {e}"
            )

    if "corridor_shp_bytes" in st.session_state:

        st.download_button(
            "Download Corridor Shapefile ZIP",
            st.session_state[
                "corridor_shp_bytes"
            ],
            file_name="corridors_shapefile.zip",
            mime="application/zip",
            key="download_corridor_shp"
        )
# -----------------------------
# 4. Upload crash data
# -----------------------------

st.header("4. Upload and filter crash data")

area_name = st.session_state.get(
    "area_name",
    "Study Area"
)

route_col = st.session_state.get(
    "route_col",
    "FULLNAME"
)

segment_id_col = st.session_state.get(
    "segment_id_col",
    None
)

crash_file = st.file_uploader(
    "Upload crash CSV or Excel file",
    type=["csv", "xlsx", "xls"],
    key="crash_file"
)

crashes = st.session_state.get(
    "crashes",
    None
)

if crash_file:

    crash_df = load_crash_file(
        crash_file
    )

    try:

        crashes = crash_points(
            crash_df
        ).to_crs(4326)

        if selected_boundary is not None:

            crashes = (
                gpd.sjoin(
                    crashes,
                    selected_boundary[["geometry"]],
                    predicate="within"
                )
                .drop(
                    columns=["index_right"]
                )
            )

        st.subheader("Crash data filters")

        filter_cols = find_filter_columns(
            crashes
        )

        if filter_cols:

            for col in filter_cols:

                values = sorted(
                    crashes[col]
                    .dropna()
                    .astype(str)
                    .unique()
                )

                selected_values = st.multiselect(
                    f"Filter by {col}",
                    values,
                    default=values,
                    key=f"filter_{col}"
                )

                crashes = crashes[
                    crashes[col]
                    .astype(str)
                    .isin(selected_values)
                ].copy()

        else:

            st.info(
                "No Year or Crash_Type style filter columns detected."
            )

        st.session_state[
            "crashes"
        ] = crashes

        st.success(
            f"Crash points loaded after filters: {len(crashes)}"
        )

    except Exception as e:

        st.error(
            str(e)
        )

if crashes is not None:

    fmap = make_map(
        boundary=selected_boundary,
        roads=selected_roads,
        signals=signals_clean,
        corridors=corridors,
        crashes=crashes
    )

    st_folium(
        fmap,
        width=1200,
        height=600,
        key="crash_upload_map"
    )


# -----------------------------
# 5. Classify crashes
# -----------------------------

st.header("5. Classify crashes")

from modules.crash_classification import (
    create_intersection_units,
    create_corridor_units,
    create_road_segment_units,
    assign_crashes_to_units,
    summarize_kabco,
)

if crashes is not None:

    crash_analysis_type = st.radio(
        "Select crash analysis type",
        [
            "Intersection crashes",
            "Corridor crashes",
            "Road segment crashes"
        ]
    )

    spatial_units = None
    assigned_crashes = None
    kabco_result = None

    if crash_analysis_type == "Intersection crashes":

        intersection_buffer_ft = st.number_input(
            "Intersection buffer size, feet",
            min_value=25,
            max_value=1000,
            value=250,
            step=25
        )

        if signals_clean is None:

            st.warning(
                "Generate signals first."
            )

        elif st.button("Classify Intersection Crashes"):

            spatial_units = create_intersection_units(
                signals_clean,
                buffer_ft=intersection_buffer_ft
            )

            assigned_crashes = assign_crashes_to_units(
                crashes,
                spatial_units,
                unit_id_col="UnitID",
                method="within"
            )

            kabco_result = summarize_kabco(
                assigned_crashes,
                unit_id_col="UnitID"
            )

            st.session_state[
                "spatial_units"
            ] = spatial_units

            st.session_state[
                "assigned_crashes"
            ] = assigned_crashes

            st.session_state[
                "kabco_result"
            ] = kabco_result

            st.session_state[
                "analysis_type"
            ] = "Intersection"

    elif crash_analysis_type == "Corridor crashes":

        if corridors is None:

            st.warning(
                "Build corridors first."
            )

        elif st.button("Classify Corridor Crashes"):

            spatial_units = create_corridor_units(
                corridors
            )

            assigned_crashes = assign_crashes_to_units(
                crashes,
                spatial_units,
                unit_id_col="UnitID",
                method="within"
            )

            kabco_result = summarize_kabco(
                assigned_crashes,
                unit_id_col="UnitID"
            )

            st.session_state[
                "spatial_units"
            ] = spatial_units

            st.session_state[
                "assigned_crashes"
            ] = assigned_crashes

            st.session_state[
                "kabco_result"
            ] = kabco_result

            st.session_state[
                "analysis_type"
            ] = "Corridor"

    elif crash_analysis_type == "Road segment crashes":

        segment_unit_method = st.radio(
            "Road segment unit method",
            [
                "Create equal-length segments",
                "Use uploaded road segments"
            ],
            horizontal=True
        )

        segment_search_distance_ft = st.number_input(
            "Maximum crash distance from segment, feet",
            min_value=10,
            max_value=500,
            value=100,
            step=10
        )

        if selected_roads is None:

            st.warning(
                "Select roads first."
            )

        elif segment_unit_method == "Create equal-length segments":

            segment_length_ft = st.number_input(
                "Road segment length, feet",
                min_value=50,
                max_value=5280,
                value=500,
                step=50
            )

            if st.button("Classify Road Segment Crashes"):

                spatial_units = create_road_segment_units(
                    selected_roads,
                    segment_length_ft=segment_length_ft
                )

                assigned_crashes = assign_crashes_to_units(
                    crashes,
                    spatial_units,
                    unit_id_col="UnitID",
                    method="nearest",
                    search_distance_ft=segment_search_distance_ft
                )

                kabco_result = summarize_kabco(
                    assigned_crashes,
                    unit_id_col="UnitID"
                )

                st.session_state["spatial_units"] = spatial_units
                st.session_state["assigned_crashes"] = assigned_crashes
                st.session_state["kabco_result"] = kabco_result
                st.session_state["analysis_type"] = "Road Segment"
                st.session_state["segment_unit_method"] = "Equal Length"

        elif segment_unit_method == "Use uploaded road segments":

            if st.button("Classify Uploaded Road Segment Crashes"):

                spatial_units = selected_roads.copy()

                segment_id_col = st.session_state.get(
                    "segment_id_col",
                    None
                )

                if segment_id_col is None or segment_id_col not in spatial_units.columns:
                    st.error(
                        "Segment ID column is missing. Please select a unique segment ID column in Section 1."
                    )
                    st.stop()

                spatial_units["UnitID"] = spatial_units[
                    segment_id_col
                ].astype(str)

                spatial_units["UnitType"] = "Road Segment"

                spatial_units["SegmentID"] = spatial_units["UnitID"]

                assigned_crashes = assign_crashes_to_units(
                    crashes,
                    spatial_units,
                    unit_id_col="UnitID",
                    method="nearest",
                    search_distance_ft=segment_search_distance_ft
                )

                kabco_result = summarize_kabco(
                    assigned_crashes,
                    unit_id_col="UnitID"
                )

                st.session_state["spatial_units"] = spatial_units
                st.session_state["assigned_crashes"] = assigned_crashes
                st.session_state["kabco_result"] = kabco_result
                st.session_state["analysis_type"] = "Uploaded Road Segment"
                st.session_state["segment_unit_method"] = "Uploaded Road Segments"

# -----------------------------
# 6. Crash summary, map, and downloads
# -----------------------------

def prepare_for_shapefile(gdf):

    keep_cols = [
        c for c in [
            "CrashID",
            "SourceCrashID",
            "UnitID",
            "UnitType",
            "IntersectionID",
            "SegmentID",
            "CorridorID",
            "Route",
            route_col,
            segment_id_col,
            "FULLNAME",
            "FromMile",
            "ToMile",
            "Length_Miles",
            "Area_SqMi",
            "KABCO",
            "Severity",
            "Total",
            "CrashCount",
            "CrashDensity",
            "geometry"
        ]
        if c is not None and c in gdf.columns
    ]

    return gdf[keep_cols].copy()


def add_density_to_spatial_units(spatial_units_map):

    spatial_units_map = spatial_units_map.copy()

    spatial_units_proj = spatial_units_map.to_crs(epsg=3857)

    spatial_units_map["Length_Miles"] = (
        spatial_units_proj.geometry.length / 1609.344
    )

    spatial_units_map["Area_SqMi"] = (
        spatial_units_proj.geometry.area / 2589988.110336
    )

    spatial_units_map["CrashDensity"] = 0.0

    if "UnitType" in spatial_units_map.columns:

        line_mask = spatial_units_map["UnitType"].isin(
            [
                "Segment",
                "Corridor",
                "Sliding Window",
                "Road Segment"
            ]
        )

        area_mask = spatial_units_map["UnitType"].isin(
            [
                "Intersection",
                "Intersection Buffer"
            ]
        )

        spatial_units_map.loc[line_mask, "CrashDensity"] = np.where(
            spatial_units_map.loc[line_mask, "Length_Miles"] > 0,
            spatial_units_map.loc[line_mask, "CrashCount"] /
            spatial_units_map.loc[line_mask, "Length_Miles"],
            0
        )

        spatial_units_map.loc[area_mask, "CrashDensity"] = np.where(
            spatial_units_map.loc[area_mask, "Area_SqMi"] > 0,
            spatial_units_map.loc[area_mask, "CrashCount"] /
            spatial_units_map.loc[area_mask, "Area_SqMi"],
            0
        )

        other_mask = ~(line_mask | area_mask)

        spatial_units_map.loc[other_mask, "CrashDensity"] = (
            spatial_units_map.loc[other_mask, "CrashCount"]
        )

    else:

        geom_types = spatial_units_map.geometry.geom_type

        line_mask = geom_types.isin(
            [
                "LineString",
                "MultiLineString"
            ]
        )

        polygon_mask = geom_types.isin(
            [
                "Polygon",
                "MultiPolygon"
            ]
        )

        point_mask = geom_types.isin(
            [
                "Point",
                "MultiPoint"
            ]
        )

        spatial_units_map.loc[line_mask, "CrashDensity"] = np.where(
            spatial_units_map.loc[line_mask, "Length_Miles"] > 0,
            spatial_units_map.loc[line_mask, "CrashCount"] /
            spatial_units_map.loc[line_mask, "Length_Miles"],
            0
        )

        spatial_units_map.loc[polygon_mask, "CrashDensity"] = np.where(
            spatial_units_map.loc[polygon_mask, "Area_SqMi"] > 0,
            spatial_units_map.loc[polygon_mask, "CrashCount"] /
            spatial_units_map.loc[polygon_mask, "Area_SqMi"],
            0
        )

        spatial_units_map.loc[point_mask, "CrashDensity"] = (
            spatial_units_map.loc[point_mask, "CrashCount"]
        )

    spatial_units_map["CrashDensity"] = (
        spatial_units_map["CrashDensity"]
        .replace([np.inf, -np.inf], 0)
        .fillna(0)
    )

    return spatial_units_map


def make_density_colormap(
    gdf,
    density_col="CrashDensity"
):

    values = (
        pd.to_numeric(
            gdf[density_col],
            errors="coerce"
        )
        .fillna(0)
    )

    vmax = values.quantile(
        0.95
    )

    if vmax <= 0:

        vmax = 1

    cmap = cm.LinearColormap(
        colors=[
            "green",
            "yellow",
            "orange",
            "red"
        ],
        vmin=0,
        vmax=float(vmax)
    )

    cmap.caption = (
        "Crash Density: "
        "Green = Low, Red = High"
    )

    return cmap


def get_density_color(value, cmap):

    if value is None:
        value = 0

    try:
        if np.isnan(value):
            value = 0
    except Exception:
        value = 0

    return cmap(float(value))


st.header("6. Crash summary, map, and downloads")

spatial_units = st.session_state.get(
    "spatial_units",
    None
)

assigned_crashes = st.session_state.get(
    "assigned_crashes",
    None
)

kabco_result = st.session_state.get(
    "kabco_result",
    None
)

analysis_type = st.session_state.get(
    "analysis_type",
    None
)

if spatial_units is not None and assigned_crashes is not None:

    crash_counts = (
        assigned_crashes
        .groupby("UnitID")
        .size()
        .reset_index(name="CrashCount")
    )

    spatial_units_map = spatial_units.merge(
        crash_counts,
        on="UnitID",
        how="left"
    )

    spatial_units_map["CrashCount"] = (
        spatial_units_map["CrashCount"]
        .fillna(0)
        .astype(int)
    )

    spatial_units_map = add_density_to_spatial_units(
        spatial_units_map
    )

    st.subheader(
        f"{analysis_type} Spatial Units"
    )

    units_table = spatial_units_map.copy()
    units_table["GeometryType"] = units_table.geometry.geom_type

    raw_display_unit_cols = [
        "UnitType",
        "UnitID",
        "IntersectionID",
        "SegmentID",
        "CorridorID",
        "Route",
        route_col,
        segment_id_col,
        "FULLNAME",
        "RoadName1",
        "RoadName2",
        "FromMile",
        "ToMile",
        "Length_Miles",
        "Area_SqMi",
        "CrashCount",
        "CrashDensity",
        "GeometryType"
    ]

    display_unit_cols = []

    for c in raw_display_unit_cols:
        if c is not None and c in units_table.columns and c not in display_unit_cols:
            display_unit_cols.append(c)

    units_table = units_table[
        display_unit_cols
    ]

    st.dataframe(
        units_table,
        width="stretch"
    )

    st.subheader("Assigned Crashes")

    assigned_table = assigned_crashes.copy()
    assigned_table["Latitude"] = assigned_table.geometry.y
    assigned_table["Longitude"] = assigned_table.geometry.x

    raw_display_crash_cols = [
        "CrashID",
        "SourceCrashID",
        "UnitType",
        "UnitID",
        "IntersectionID",
        "SegmentID",
        "CorridorID",
        "Route",
        route_col,
        segment_id_col,
        "FULLNAME",
        "Latitude",
        "Longitude",
        "DistToUnit_M",
        "KABCO",
        "kabco",
        "Severity",
        "severity",
        "CRASH_SEVERITY",
        "Crash Severity",
        "INJURY_SEVERITY",
        "injury_severity"
    ]

    display_crash_cols = []

    for c in raw_display_crash_cols:
        if c is not None and c in assigned_table.columns and c not in display_crash_cols:
            display_crash_cols.append(c)

    assigned_table = assigned_table[
        display_crash_cols
    ]

    st.dataframe(
        assigned_table,
        width="stretch"
    )

    if kabco_result is not None:

        st.subheader("KABCO / Crash Summary")

        st.dataframe(
            kabco_result,
            width="stretch"
        )

        st.download_button(
            "Download Crash Summary CSV",
            kabco_result.to_csv(index=False),
            file_name="crash_summary.csv",
            mime="text/csv",
            key=f"download_summary_{analysis_type}"
        )

    st.download_button(
        "Download Spatial Units CSV",
        units_table.to_csv(index=False),
        file_name="spatial_units.csv",
        mime="text/csv",
        key=f"download_units_csv_{analysis_type}"
    )

    st.download_button(
        "Download Assigned Crashes CSV",
        assigned_table.to_csv(index=False),
        file_name="assigned_crashes.csv",
        mime="text/csv",
        key=f"download_assigned_csv_{analysis_type}"
    )

    st.subheader("Download Geometry Files")

    geojson_key = f"units_with_density_geojson_{analysis_type}"

    if st.button(
        "Prepare Spatial Units With Crash Density GeoJSON",
        key=f"prepare_{geojson_key}"
    ):

        try:

            geojson_gdf = make_json_safe_gdf(
                spatial_units_map.to_crs(4326)
            )

            geojson_bytes = (
                geojson_gdf
                .to_json()
                .encode("utf-8")
            )

            st.session_state[
                geojson_key
            ] = geojson_bytes

            st.success(
                "Spatial units with crash density GeoJSON ready."
            )

        except Exception as e:

            st.error(
                f"Could not create spatial units GeoJSON: {e}"
            )

    if geojson_key in st.session_state:

        st.download_button(
            "Download Spatial Units With Crash Density GeoJSON",
            st.session_state[
                geojson_key
            ],
            file_name="spatial_units_with_crash_density.geojson",
            mime="application/geo+json",
            key=f"download_{geojson_key}"
        )

    st.subheader("Crash Assignment Map")

    unit_display_option = st.radio(
        "Spatial unit display option",
        [
            "Show crashes with all spatial units",
            "Show crashes with spatial units that have crashes only"
        ],
        index=0
    )

    if unit_display_option == "Show crashes with spatial units that have crashes only":

        spatial_units_map_for_display = spatial_units_map[
            spatial_units_map["CrashCount"] > 0
        ].copy()

    else:

        spatial_units_map_for_display = spatial_units_map.copy()

    # Filter signals when only showing spatial units with crashes
    if unit_display_option == "Show crashes with spatial units that have crashes only":
        signals_for_display = filter_points_to_units(
            signals_clean,
            spatial_units_map_for_display,
            buffer_m=20
        )
    else:
        signals_for_display = signals_clean

    st.markdown("### Map layers")

    map_layer_options = [
        "Boundary",
        "Roads",
        "Signals",
        "Crash Density Spatial Units",
        "Assigned Crashes"
    ]

    selected_map_layers = st.multiselect(
        "Select layers to show on the crash assignment map",
        map_layer_options,
        default=[
            "Boundary",
            "Roads",
            "Signals",
            "Crash Density Spatial Units",
            "Assigned Crashes"
        ]
    )

    boundary_layer = selected_boundary if "Boundary" in selected_map_layers else None
    roads_layer = selected_roads if "Roads" in selected_map_layers else None
    signals_layer = signals_for_display if "Signals" in selected_map_layers else None
    spatial_units_layer = (
        spatial_units_map_for_display
        if "Crash Density Spatial Units" in selected_map_layers
        else None
    )
    crashes_layer = assigned_crashes if "Assigned Crashes" in selected_map_layers else None

    density_cmap = make_density_colormap(
        spatial_units_map_for_display
    )

    fmap = make_map(
        boundary=boundary_layer,
        roads=roads_layer,
        signals=signals_layer,
        corridors=None,
        spatial_units=spatial_units_layer,
        crashes=crashes_layer,
        density_cmap=density_cmap
    )

    if spatial_units_layer is not None:
        density_cmap.add_to(fmap)

    fmap = add_map_elements(fmap)

    st.markdown("### Download map / layers")

    download_layer_options = st.multiselect(
        "Select layers to download",
        map_layer_options,
        default=[
            "Crash Density Spatial Units",
            "Assigned Crashes"
        ]
    )

    download_layers = {
        "boundary": selected_boundary if "Boundary" in download_layer_options else None,
        "roads": selected_roads if "Roads" in download_layer_options else None,
        "signals": signals_for_display if "Signals" in download_layer_options else None,
        "crash_density_spatial_units": (
            spatial_units_map_for_display
            if "Crash Density Spatial Units" in download_layer_options
            else None
        ),
        "assigned_crashes": assigned_crashes if "Assigned Crashes" in download_layer_options else None,
    }

    selected_download_layers = {
        k: v for k, v in download_layers.items()
        if v is not None and not v.empty
    }

    pdf_bytes = create_static_map_pdf(
        boundary=boundary_layer,
        roads=roads_layer,
        signals=signals_layer,
        spatial_units=spatial_units_layer,
        crashes=crashes_layer,
        title=f"{analysis_type} Crash Assignment Map"
    )

    st.download_button(
        "Download Current Map PDF",
        data=pdf_bytes,
        file_name="crash_assignment_map.pdf",
        mime="application/pdf",
        key=f"download_current_map_pdf_{analysis_type}"
    )

    if selected_download_layers:

        layer_zip_bytes = geojson_zip_for_layers(
            selected_download_layers
        )

        st.download_button(
            "Download Selected Layers GeoJSON ZIP",
            data=layer_zip_bytes,
            file_name="selected_crash_assignment_layers.zip",
            mime="application/zip",
            key=f"download_selected_layers_{analysis_type}"
        )


    st_folium(
        fmap,
        width=1200,
        height=600,
        key=(
            "crash_assignment_map_"
            + str(analysis_type)
            + "_"
            + str(unit_display_option)
            + "_"
            + "_".join(selected_map_layers)
            + "_"
            + str(len(spatial_units_map_for_display))
            + "_"
            + str(len(assigned_crashes))
        )
    )
