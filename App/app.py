import streamlit as st
from streamlit_folium import st_folium
import geopandas as gpd
import folium

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


st.set_page_config(
    page_title="Corridor Crash Tool",
    layout="wide"
)

st.title("Local Corridor Crash Analysis Tool")

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


def make_map(
    boundary=None,
    roads=None,
    signals=None,
    corridors=None,
    spatial_units=None,
    crashes=None
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

    if roads is not None:
        road_lines = roads[
            roads.geometry.geom_type.isin(
                ["LineString", "MultiLineString"]
            )
        ].copy()

        if not road_lines.empty:

            if "RoadClass" in road_lines.columns:
                groups = road_lines.groupby(
                    "RoadClass"
                )
            else:
                groups = [
                    ("Unknown", road_lines)
                ]

            for road_class, sub in groups:

                folium.GeoJson(
                    sub,
                    name=f"{road_class}",
                    style_function=lambda feature,
                    road_class=road_class: {
                        "color": road_class_color(
                            road_class
                        ),
                        "weight": 3,
                        "opacity": 0.9,
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=[
                            c for c in [
                                "FULLNAME",
                                "RoadClass",
                                "RoadType"
                            ]
                            if c in sub.columns
                        ]
                    )
                ).add_to(fmap)
    corridors = clean_for_map(corridors)

    if corridors is not None:
        id_field = None

        if "CorridorID" in corridors.columns:
            id_field = "CorridorID"
        elif "corridor_id" in corridors.columns:
            id_field = "corridor_id"

        if id_field is not None:
            for corridor_id, sub in corridors.groupby(id_field):
                color = id_color(corridor_id)

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

    if spatial_units is not None:
        if "UnitID" in spatial_units.columns:
            for unit_id, sub in spatial_units.groupby("UnitID"):
                color = id_color(unit_id)

                tooltip_fields = [
                    c for c in [
                        "UnitID",
                        "UnitType",
                        "CrashCount",
                        "IntersectionID",
                        "SegmentID",
                        "CorridorID",
                        "Route",
                        "FULLNAME",
                        "RoadName1",
                        "RoadName2"
                    ]
                    if c in sub.columns
                ]

                folium.GeoJson(
                    sub,
                    name=str(unit_id),
                    style_function=lambda feature, color=color: {
                        "color": color,
                        "fillColor": color,
                        "weight": 3,
                        "fillOpacity": 0.30,
                        "opacity": 0.9,
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=tooltip_fields
                    ) if tooltip_fields else None,
                ).add_to(fmap)

        else:
            folium.GeoJson(
                spatial_units,
                name="Spatial Units",
                style_function=lambda feature: {
                    "color": "purple",
                    "fillColor": "purple",
                    "weight": 3,
                    "fillOpacity": 0.25,
                },
            ).add_to(fmap)

    signals = clean_for_map(signals)

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

    folium.LayerControl().add_to(fmap)

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
# 1. Upload TIGER files
# -----------------------------

st.header("1. Upload TIGER files")

col1, col2 = st.columns(2)

with col1:
    roads_file = st.file_uploader(
        "Upload county TIGER roads ZIP",
        type=["zip", "gpkg", "geojson", "json"],
        key="roads_file"
    )

with col2:
    places_file = st.file_uploader(
        "Upload state PLACE ZIP",
        type=["zip", "gpkg", "geojson", "json"],
        key="places_file"
    )

roads = None
places = None
selected_roads = None
selected_boundary = None

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

        city_roads = roads.copy()

        selected_boundary = gpd.GeoDataFrame(
            geometry=[
                roads.geometry.union_all().convex_hull
            ],
            crs=roads.crs
        )

    road_classes = get_road_classes(
        city_roads
    )

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

    if "RoadClass" in selected_roads.columns:
        selected_roads["RoadClass"] = (
            selected_roads["RoadClass"]
            .fillna("Unknown")
        )

    if "RoadType" in selected_roads.columns:
        selected_roads["RoadType"] = (
            selected_roads["RoadType"]
            .fillna("Unknown")
        )

    st.session_state["selected_boundary"] = selected_boundary
    st.session_state["selected_roads"] = selected_roads

    if st.button("Reset generated layers"):

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
            if k in st.session_state:
                del st.session_state[k]

        st.rerun()

    st.write(f"Selected roads: {len(selected_roads)}")

    if not selected_roads.empty:

        road_table_cols = [
            c for c in [
                "FULLNAME",
                "RoadClass",
                "RoadType",
                "RTTYP",
                "MTFCC"
            ]
            if c in selected_roads.columns
        ]

        with st.expander("Selected road attributes", expanded=False):

            st.dataframe(
                selected_roads[
                    road_table_cols
                ].drop_duplicates(),
                use_container_width=True
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

            signals_clean["City"] = city_name

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
        use_container_width=True
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

corridors = st.session_state.get("corridors", None)
signals_with_corridor = st.session_state.get("signals_with_corridor", None)
corridor_summary = st.session_state.get("corridor_signal_summary", None)

if selected_roads is not None and signals_clean is not None:

    build_corr = st.checkbox(
        "Build corridors from selected signals and TIGER roads"
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

        with st.spinner("Assigning CorridorID and building corridor polygons..."):

            signals_with_corridor = assign_corridor_ids_to_signals(
                signals_clean,
                selected_roads,
                city_name=city_name,
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
                city_name=city_name
            )

            st.session_state["signals_with_corridor"] = signals_with_corridor
            st.session_state["corridor_signal_summary"] = corridor_summary
            st.session_state["corridors"] = corridors

        st.success(f"Corridors built: {len(corridors)}")

if signals_with_corridor is not None:

    st.subheader("Signals With CorridorID")

    signal_corridor_table = signals_with_corridor.copy()

    if "SignalID" not in signal_corridor_table.columns:
        signal_corridor_table["SignalID"] = signal_corridor_table.index + 1

    if "City" not in signal_corridor_table.columns:
        signal_corridor_table["City"] = city_name

    signal_corridor_table["Latitude"] = signal_corridor_table.geometry.y
    signal_corridor_table["Longitude"] = signal_corridor_table.geometry.x

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

    signal_corridor_table = signal_corridor_table[display_cols]

    st.dataframe(
        signal_corridor_table,
        use_container_width=True
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
        use_container_width=True
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

crash_file = st.file_uploader(
    "Upload crash CSV or Excel file",
    type=["csv", "xlsx", "xls"],
    key="crash_file"
)

crashes = st.session_state.get("crashes", None)

if crash_file:
    crash_df = load_crash_file(crash_file)

    try:
        crashes = crash_points(crash_df).to_crs(4326)

        if selected_boundary is not None:
            crashes = (
                gpd.sjoin(
                    crashes,
                    selected_boundary[["geometry"]],
                    predicate="within"
                )
                .drop(columns=["index_right"])
            )

        st.subheader("Crash data filters")

        filter_cols = find_filter_columns(crashes)

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
                    crashes[col].astype(str).isin(selected_values)
                ].copy()
        else:
            st.info("No Year or Crash_Type style filter columns detected.")

        st.session_state["crashes"] = crashes

        st.success(
            f"Crash points loaded after filters: {len(crashes)}"
        )

    except Exception as e:
        st.error(str(e))

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
            st.warning("Generate signals first.")

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

            st.session_state["spatial_units"] = spatial_units
            st.session_state["assigned_crashes"] = assigned_crashes
            st.session_state["kabco_result"] = kabco_result
            st.session_state["analysis_type"] = "Intersection"

    elif crash_analysis_type == "Corridor crashes":

        if corridors is None:
            st.warning("Build corridors first.")

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

            st.session_state["spatial_units"] = spatial_units
            st.session_state["assigned_crashes"] = assigned_crashes
            st.session_state["kabco_result"] = kabco_result
            st.session_state["analysis_type"] = "Corridor"

    elif crash_analysis_type == "Road segment crashes":

        segment_length_ft = st.number_input(
            "Road segment length, feet",
            min_value=50,
            max_value=5280,
            value=500,
            step=50
        )

        segment_search_distance_ft = st.number_input(
            "Maximum crash distance from segment, feet",
            min_value=10,
            max_value=500,
            value=100,
            step=10
        )

        if selected_roads is None:
            st.warning("Select roads first.")

        elif st.button("Classify Road Segment Crashes"):

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


# -----------------------------
# 6. Crash summary, map, and downloads
# -----------------------------

def prepare_for_shapefile(gdf):
    keep_cols = [
        c for c in [
            "CrashID", "UnitID", "UnitType", "IntersectionID",
            "SegmentID", "CorridorID", "Route", "FULLNAME",
            "KABCO", "Severity", "Total", "CrashCount", "geometry"
        ]
        if c in gdf.columns
    ]

    return gdf[keep_cols].copy()


def unit_color(unit_id):
    try:
        idx = int(str(unit_id).split("_")[-1])
    except Exception:
        idx = abs(hash(str(unit_id)))

    return id_color(idx)


st.header("6. Crash summary, map, and downloads")

spatial_units = st.session_state.get("spatial_units", None)
assigned_crashes = st.session_state.get("assigned_crashes", None)
kabco_result = st.session_state.get("kabco_result", None)
analysis_type = st.session_state.get("analysis_type", None)

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

    st.subheader(f"{analysis_type} Spatial Units")

    units_table = spatial_units_map.copy()
    units_table["GeometryType"] = units_table.geometry.geom_type

    display_unit_cols = [
        c for c in [
            "UnitType", "UnitID", "IntersectionID", "SegmentID",
            "CorridorID", "Route", "FULLNAME", "RoadName1",
            "RoadName2", "CrashCount", "GeometryType"
        ]
        if c in units_table.columns
    ]

    units_table = units_table[display_unit_cols]

    st.dataframe(
        units_table,
        use_container_width=True
    )

    st.subheader("Assigned Crashes")

    assigned_table = assigned_crashes.copy()
    assigned_table["Latitude"] = assigned_table.geometry.y
    assigned_table["Longitude"] = assigned_table.geometry.x

    display_crash_cols = [
        c for c in [
            "CrashID",
            "SourceCrashID",
            "UnitType",
            "UnitID",
            "IntersectionID",
            "SegmentID",
            "CorridorID",
            "Route",
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
        if c in assigned_table.columns
    ]

    assigned_table = assigned_table[display_crash_cols]

    st.dataframe(
        assigned_table,
        use_container_width=True
    )

    if kabco_result is not None:

        st.subheader("KABCO / Crash Summary")

        st.dataframe(
            kabco_result,
            use_container_width=True
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

    geojson_key = f"units_with_count_geojson_{analysis_type}"

    if st.button(
        "Prepare Spatial Units With Crash Count GeoJSON",
        key=f"prepare_{geojson_key}"
    ):

        try:
            geojson_bytes = (
                spatial_units_map
                .to_crs(4326)
                .to_json()
                .encode("utf-8")
            )

            st.session_state[geojson_key] = geojson_bytes

            st.success(
                "Spatial units with crash count GeoJSON ready."
            )

        except Exception as e:
            st.error(
                f"Could not create spatial units GeoJSON: {e}"
            )

    if geojson_key in st.session_state:

        st.download_button(
            "Download Spatial Units With Crash Count GeoJSON",
            st.session_state[geojson_key],
            file_name="spatial_units_with_crash_count.geojson",
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

    map_base = spatial_units_map_for_display

    if map_base is None or map_base.empty:
        map_base = assigned_crashes

    if map_base is None or map_base.empty:
        map_base = selected_roads

    map_base = map_base.to_crs(4326)
    center_geom = map_base.geometry.union_all().centroid

    fmap = folium.Map(
        location=[center_geom.y, center_geom.x],
        zoom_start=13,
        tiles="OpenStreetMap"
    )

    if selected_boundary is not None and not selected_boundary.empty:
        folium.GeoJson(
            selected_boundary.to_crs(4326),
            name="Selected Boundary",
            style_function=lambda feature: {
                "color": "black",
                "weight": 2,
                "fillOpacity": 0.02
            }
        ).add_to(fmap)

    if selected_roads is not None and not selected_roads.empty:
        road_lines = selected_roads[
            selected_roads.geometry.geom_type.isin(
                ["LineString", "MultiLineString"]
            )
        ].copy()

        folium.GeoJson(
            road_lines.to_crs(4326),
            name="Selected Roads",
            style_function=lambda feature: {
                "color": "gray",
                "weight": 2,
                "opacity": 0.7
            }
        ).add_to(fmap)

    if (
        spatial_units_map_for_display is not None
        and not spatial_units_map_for_display.empty
    ):

        units_4326 = spatial_units_map_for_display.to_crs(4326)

        for unit_id, sub in units_4326.groupby("UnitID"):

            color = unit_color(unit_id)

            folium.GeoJson(
                sub,
                name=str(unit_id),
                style_function=lambda feature, color=color: {
                    "color": color,
                    "fillColor": color,
                    "weight": 3,
                    "fillOpacity": 0.30,
                    "opacity": 0.9
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=[
                        "UnitID",
                        "UnitType",
                        "CrashCount"
                    ],
                    aliases=[
                        "Unit ID:",
                        "Type:",
                        "Crashes:"
                    ]
                )
            ).add_to(fmap)

    if assigned_crashes is not None and not assigned_crashes.empty:

        crashes_4326 = assigned_crashes.to_crs(4326)

        crash_group = folium.FeatureGroup(
            name="Assigned Crashes"
        )

        for _, row in crashes_4326.iterrows():

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
                    popup_text += f"UnitID: {row['UnitID']}<br>"

                folium.CircleMarker(
                    location=[geom.y, geom.x],
                    radius=4,
                    color="black",
                    weight=1,
                    fill=True,
                    fill_opacity=0.8,
                    popup=popup_text
                ).add_to(crash_group)

        crash_group.add_to(fmap)

    folium.LayerControl().add_to(fmap)

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
            + str(len(spatial_units_map_for_display))
            + "_"
            + str(len(assigned_crashes))
        )
    )
