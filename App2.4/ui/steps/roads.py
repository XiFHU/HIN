"""Step 1 road upload UI."""

import time

from modules.roads import (
    DEFAULT_OSM_HIGHWAY_CLASS_MAPPING,
    OSM_FUNCTIONAL_CLASSES,
    apply_osm_highway_mapping,
    fetch_osm_roads_for_place,
    suggest_osm_places,
)
from modules.io_utils import UPLOAD_READER_VERSION



def _candidate_road_class_columns(gdf):
    """Return all user-selectable attribute columns for road filtering."""
    if gdf is None or gdf.empty:
        return []

    return [
        c for c in gdf.columns
        if c != "geometry"
    ]


def _generate_mileposts_for_road_source(roads, route_col, segment_id_col):
    """Generate and validate identical milepost fields for every road source."""
    result = generate_from_to_mile(
        roads=roads,
        route_col=route_col,
        segment_id_col=segment_id_col,
        direction_method="Auto Detect",
        start_mile=0.0,
    )

    required_output_columns = [
        "FromMile",
        "ToMile",
        "SegmentLength_Mile",
    ]
    missing_output_columns = [
        column_name
        for column_name in required_output_columns
        if column_name not in result.columns
    ]
    if missing_output_columns:
        raise ValueError(
            "Milepost generation did not create required field(s): "
            + ", ".join(missing_output_columns)
        )

    return result


def _clear_downstream_results_after_road_change():
    """Clear layers/results that depend on the analysis road network."""

    for k in [
        "signals_clean",
        "signals_clean_all",
        "dropped_signal_ids",
        "applied_dropped_signal_ids",
        "signals_with_corridor",
        "signals_for_corridors",
        "corridor_signal_summary",
        "corridors",
        "final_corridors",
        "dropped_corridor_ids",
        "applied_dropped_corridor_ids",
        "corridor_roads",
        "corridor_shp_bytes",
        "spatial_units",
        "spatial_units_density_map",
        "assigned_crashes",
        "kabco_result",
        "analysis_type",
        "classified",
        "unit_col",
        "section7_results",
        "section7_original_density",
        "section7_crashes_for_map",
        "section7_route_col_s7"
    ]:
        st.session_state.pop(
            k,
            None
        )



def _render_osm_highway_mapping(osm_roads):
    """Render OSM highway-to-functional-class controls."""

    if "OSMHighway" in osm_roads.columns:
        highway_series = osm_roads["OSMHighway"]
    else:
        highway_series = []

    highway_values = sorted(
        [
            str(v)
            for v in getattr(highway_series, "dropna", lambda: highway_series)()
            if str(v).strip()
        ]
    )

    highway_values = sorted(set(highway_values))

    if not highway_values:
        st.warning(
            "No OSM highway values were found. Roads will be treated as Local Road."
        )
        return {"unknown": "Local Road"}

    st.markdown("**OSM highway classification mapping**")
    st.caption(
        "Map each OSM `highway` value to the functional class used by the analysis. "
        "Values mapped to 'Omit From Analysis' are excluded before FromMile/ToMile generation."
    )

    mapping = {}

    header_left, header_right = st.columns([1.2, 2.0])
    with header_left:
        st.markdown("**OSM highway**")
    with header_right:
        st.markdown("**Functional class**")

    for highway_value in highway_values:
        default_class = DEFAULT_OSM_HIGHWAY_CLASS_MAPPING.get(
            highway_value,
            "Local Road"
        )

        if default_class not in OSM_FUNCTIONAL_CLASSES:
            default_class = "Local Road"

        key = (
            "osm_highway_class_"
            + highway_value.replace(" ", "_").replace("/", "_").replace("-", "_")
        )

        default_index = OSM_FUNCTIONAL_CLASSES.index(default_class)

        col_left, col_right = st.columns([1.2, 2.0])
        with col_left:
            st.write(highway_value)
        with col_right:
            mapping[highway_value] = st.selectbox(
                label=f"Functional class for {highway_value}",
                options=OSM_FUNCTIONAL_CLASSES,
                index=default_index,
                key=key,
                label_visibility="collapsed",
            )

    return mapping


def _apply_road_network_filter(base_roads):
    """Road Network Filter.

    This controls the road network used for analysis.
    The filtered roads are stored in st.session_state["selected_roads"].
    """

    if base_roads is None or base_roads.empty:
        st.session_state["roads_class_display"] = None
        st.session_state["road_class_layer_enabled"] = False

        st.session_state.pop(
            "analysis_roads",
            None
        )

        return None

    roads_class_display = None

    with st.expander(
        "Road Network Filter",
        expanded=False
    ):

        st.caption(
            "Use this section to filter the road network used for analysis. "
            "Signals, corridors, crash assignment, segments, and sliding-window "
            "analysis will use the filtered road network."
        )

        enable_filter = st.checkbox(
            "Enable Road Network Filter",
            value=bool(
                st.session_state.get(
                    "road_class_layer_enabled",
                    False
                )
            ),
            key="road_class_layer_enabled"
        )
        if enable_filter:
            st.session_state["keep_data_setup_open"] = True

        class_cols = _candidate_road_class_columns(
            base_roads
        )

        if not enable_filter:
            st.info(
                "Road Network Filter is off. The full road network will be used for analysis."
            )

            st.session_state["roads_class_display"] = None
            st.session_state["show_roads_class_type"] = False

            st.session_state[
                "selected_roads"
            ] = base_roads.copy()

            previous_signature = st.session_state.get(
                "analysis_road_filter_signature",
                None
            )

            current_signature = (
                "FILTER_OFF",
                "",
                ()
            )
            if previous_signature != current_signature:
                _clear_downstream_results_after_road_change()

            st.session_state[
                "analysis_road_filter_signature"
            ] = current_signature

            st.session_state.pop(
                "analysis_roads",
                None
            )

            st.session_state.pop(
                "analysis_road_class_col",
                None
            )

            st.session_state.pop(
                "analysis_road_class_values",
                None
            )

            return None

        st.checkbox(
            "Show Road Class/Type legend",
            value=bool(
                st.session_state.get(
                    "road_class_legend_enabled",
                    True
                )
            ),
            key="road_class_legend_enabled",
            help="When on, the road class/type legend appears on workflow maps."
        )

        if not class_cols:
            st.info(
                "No road attribute columns were found for road filtering."
            )

            st.session_state["roads_class_display"] = None
            st.session_state["show_roads_class_type"] = False

            return None

        preferred_class_col = st.session_state.get(
            "road_class_viz_col",
            ""
        )

        if preferred_class_col not in class_cols:
            if "FunctionalClass" in class_cols:
                preferred_class_col = "FunctionalClass"
            elif "RoadClass" in class_cols:
                preferred_class_col = "RoadClass"
            elif "RoadType" in class_cols:
                preferred_class_col = "RoadType"
            else:
                preferred_class_col = ""

        road_class_options = [""] + class_cols
        road_class_default_index = (
            road_class_options.index(preferred_class_col)
            if preferred_class_col in road_class_options
            else 0
        )

        road_class_col = st.selectbox(
            "Road class/type column",
            road_class_options,
            index=road_class_default_index,
            key="road_class_viz_col"
        )

        if road_class_col == "":
            st.info(
                "Select a road class/type column to filter the analysis road network."
            )

            st.session_state["roads_class_display"] = None
            st.session_state["show_roads_class_type"] = False

            st.session_state.pop(
                "analysis_roads",
                None
            )

            return None

        values = sorted(
            base_roads[road_class_col]
            .dropna()
            .astype(str)
            .unique()
        )

        default_values = st.session_state.get(
            "road_class_viz_values",
            None
        )

        if default_values is None:
            if len(values) <= 20:
                default_values = values
            else:
                default_values = values[:20]

        default_values = [
            v for v in default_values
            if v in values
        ]

        selected_values = st.multiselect(
            "Road classes/types to use for analysis",
            values,
            default=default_values,
            key="road_class_viz_values"
        )

        if selected_values:
            roads_class_display = base_roads[
                base_roads[
                    road_class_col
                ]
                .astype(str)
                .isin(selected_values)
            ].copy()
        else:
            roads_class_display = base_roads.iloc[0:0].copy()

        if not roads_class_display.empty:
            roads_class_display["RoadStyleClass"] = (
                roads_class_display[road_class_col]
                .astype(str)
                .replace(
                    {
                        "nan": "Unknown",
                        "None": "Unknown"
                    }
                )
            )

        current_signature = (
            "FILTER_ON",
            str(road_class_col),
            tuple(
                sorted(
                    [str(v) for v in selected_values]
                )
            )
        )

        previous_signature = st.session_state.get(
            "analysis_road_filter_signature",
            None
        )

        if previous_signature != current_signature:
            _clear_downstream_results_after_road_change()

        st.session_state[
            "analysis_road_filter_signature"
        ] = current_signature

        st.session_state[
            "analysis_roads"
        ] = roads_class_display.copy()
        st.session_state[
            "selected_roads"
        ] = roads_class_display.copy()

        # Do not clear downstream results on every Streamlit rerun.
        # The signature check above already clears signals/corridors only when
        # the road-class filter actually changes. Clearing here unconditionally
        # deletes signals_clean before the Corridor step can use it.
        st.session_state[
            "analysis_road_class_col"
        ] = road_class_col

        st.session_state[
            "analysis_road_class_values"
        ] = selected_values

        st.caption(
            f"Road Network Filter: {len(roads_class_display):,} "
            f"of {len(base_roads):,} roads will be used for analysis."
        )

        if roads_class_display.empty:
            st.warning(
                "No roads are selected for analysis. Select at least one road class/type."
            )

    st.session_state[
        "roads_class_display"
    ] = roads_class_display

    if roads_class_display is not None and not roads_class_display.empty:

        st.session_state[
            "show_roads_class_type"
        ] = True

        st.session_state[
            "active_map_layer"
        ] = "Roads by Class/Type"

    else:

        st.session_state[
            "show_roads_class_type"
        ] = False

    return roads_class_display


def render_roads_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    road_source = st.radio(
        "Road data source",
        [
            "Upload custom road network",
            "Use TIGER roads + PLACE boundary",
            "Use OSM roads — no upload"
        ],
        index=0,
        horizontal=False
    )

    st.session_state["road_source_label"] = road_source
    st.caption(
        "FromMile / ToMile will be generated automatically from route geometry."
    )

    roads = None
    places = None
    base_roads = None
    selected_boundary = None

    # =====================================================
    # Option A: TIGER workflow
    # =====================================================
    if road_source == "Use TIGER roads + PLACE boundary":

        st.subheader("Upload TIGER files")
        st.caption("Upload TIGER ZIP, GeoPackage, or GeoJSON files.")

        col1, col2 = st.columns(2)

        with col1:
            roads_file = st.file_uploader(
                "Upload county TIGER roads ZIP",
                type=[
                    "zip",
                    "gpkg",
                    "geojson",
                    "json"
                ],
                key="tiger_roads_file"
            )

        with col2:
            places_file = st.file_uploader(
                "Upload state PLACE ZIP",
                type=[
                    "zip",
                    "gpkg",
                    "geojson",
                    "json"
                ],
                key="places_file"
            )

        if roads_file:

            try:
                roads = load_vector(
                    roads_file
                ).to_crs(
                    4326
                )

            except Exception as e:
                st.error(
                    "Unable to read the TIGER roads upload. See the full error below."
                )
                st.exception(e)
                st.stop()

            st.success(
                "TIGER roads loaded."
            )

            use_all_roads = st.checkbox(
                "Use all roads without city clipping",
                key="tiger_use_all_roads"
            )

            city_roads = None

            if use_all_roads:

                city_name = "All Roads"
                area_name = city_name

                st.session_state[
                    "area_name"
                ] = area_name

                city_roads = roads.copy()

                selected_boundary = gpd.GeoDataFrame(
                    geometry=[
                        roads.geometry.union_all().convex_hull
                    ],
                    crs=roads.crs
                )

            elif places_file:

                try:
                    places = load_vector(
                        places_file,
                        prefer_place=True
                    ).to_crs(
                        4326
                    )

                except Exception as e:
                    st.error(
                        "Unable to read the TIGER PLACE upload. See the full error below."
                    )
                    st.exception(e)
                    st.stop()

                st.success(
                    "TIGER PLACE boundary loaded."
                )

                city_names = get_city_names_in_road_area(
                    places,
                    roads
                )

                city_name = st.selectbox(
                    "Select city",
                    city_names
                )

                area_name = city_name

                st.session_state[
                    "area_name"
                ] = area_name

                selected_boundary = places[
                    places["NAME"] == city_name
                ].copy()

                city_roads = clip_city_roads(
                    roads,
                    places,
                    city_name
                )

            else:

                st.info(
                    "Upload the state PLACE file to clip roads by city, or select "
                    "Use all roads without city clipping."
                )

            if city_roads is not None:

                base_roads = city_roads.copy()

                route_col = (
                    "FULLNAME"
                    if "FULLNAME" in base_roads.columns
                    else base_roads.columns[0]
                )

                segment_id_col = (
                    "LINEARID"
                    if "LINEARID" in base_roads.columns
                    else base_roads.columns[0]
                )

                st.session_state[
                    "selected_boundary"
                ] = selected_boundary

                st.session_state[
                    "route_col"
                ] = route_col

                st.session_state[
                    "segment_id_col"
                ] = segment_id_col

                tiger_milepost_signature = (
                    getattr(roads_file, "name", ""),
                    getattr(roads_file, "size", None),
                    str(city_name),
                    bool(use_all_roads),
                    str(route_col),
                    str(segment_id_col),
                )

                if (
                    st.session_state.get("tiger_milepost_signature")
                    != tiger_milepost_signature
                ):
                    base_roads = _generate_mileposts_for_road_source(
                        roads=base_roads,
                        route_col=route_col,
                        segment_id_col=segment_id_col
                    )

                    base_roads = base_roads.to_crs(
                        4326
                    )

                    st.session_state[
                        "base_roads"
                    ] = base_roads

                    st.session_state[
                        "selected_roads"
                    ] = base_roads

                    st.session_state[
                        "selected_boundary"
                    ] = selected_boundary

                    st.session_state.pop(
                        "analysis_roads",
                        None
                    )

                    st.session_state.pop(
                        "analysis_road_filter_signature",
                        None
                    )

                    _clear_downstream_results_after_road_change()

                    st.session_state[
                        "active_map_layer"
                    ] = "Roads"

                    st.session_state[
                        "tiger_milepost_signature"
                    ] = tiger_milepost_signature

                    st.success(
                        "TIGER roads loaded. FromMile and ToMile were generated automatically."
                    )

                else:
                    base_roads = st.session_state.get("base_roads", base_roads)

        else:

            st.info(
                "Upload the county TIGER roads file to continue."
            )

    # =====================================================
    # Option B: OSM no-upload workflow
    # =====================================================
    elif road_source == "Use OSM roads — no upload":

        st.subheader("Use OSM roads without upload")

        st.info(
            "Enter a city or study area name, then click Find matching OSM places. "
            "Choose the correct city/county/state/country from the dropdown before downloading roads."
        )

        pending_place_query = st.session_state.pop(
            "osm_place_query_pending",
            None
        )

        if "osm_place_query_input" not in st.session_state:
            st.session_state["osm_place_query_input"] = st.session_state.get(
                "osm_place_query",
                st.session_state.get("area_name", "")
            )

        if pending_place_query:
            st.session_state["osm_place_query"] = pending_place_query
            st.session_state["osm_place_query_input"] = pending_place_query

        place_query = st.text_input(
            "Study area place name",
            placeholder="Example: Aurora, CO, USA or Paris, France",
            key="osm_place_query_input"
        )

        if st.button(
            "Find matching OSM places",
            key="find_osm_place_suggestions"
        ):
            normalized_place_query = " ".join(
                str(place_query or "").split()
            ).strip()

            cached_query = st.session_state.get(
                "osm_place_suggestion_query",
                ""
            )

            cached_suggestions = st.session_state.get(
                "osm_place_suggestions",
                []
            )

            if (
                normalized_place_query
                and normalized_place_query == cached_query
                and cached_suggestions
            ):
                st.info(
                    "Using cached OSM place suggestions for this same query."
                )

            else:
                now = time.time()

                last_search_time = st.session_state.get(
                    "osm_place_search_last_time",
                    0
                )

                wait_seconds = 8
                seconds_since_last_search = now - last_search_time

                if seconds_since_last_search < wait_seconds:
                    remaining = int(
                        wait_seconds - seconds_since_last_search
                    ) + 1

                    st.warning(
                        f"Please wait about {remaining} more seconds before "
                        "searching OSM places again. This helps avoid public "
                        "geocoder rate limits."
                    )

                else:
                    st.session_state[
                        "osm_place_search_last_time"
                    ] = now

                    try:
                        suggestions = suggest_osm_places(
                            normalized_place_query,
                            limit=20
                        )

                        st.session_state[
                            "osm_place_suggestions"
                        ] = suggestions

                        st.session_state[
                            "osm_place_suggestion_query"
                        ] = normalized_place_query

                        if not suggestions:
                            st.warning(
                                "No OSM place suggestions were found. "
                                "Try a more complete query such as "
                                "'City, State/Province, Country'."
                            )
                        else:
                            st.success(
                                f"Found {len(suggestions)} possible places. "
                                "Choose the correct city/county/state/country "
                                "from the dropdown below."
                            )

                    except Exception as e:
                        st.session_state["osm_place_suggestions"] = []
                        st.session_state[
                            "osm_place_suggestion_query"
                        ] = normalized_place_query

                        st.error(
                            f"OSM place search failed: {e}"
                        )

        suggestions = st.session_state.get(
            "osm_place_suggestions",
            []
        )

        selected_place_for_download = place_query
        selected_place_info_for_download = st.session_state.get(
            "osm_selected_place_info",
            None
        )

        if suggestions:
            suggestion_options = []
            option_to_display_name = {}
            option_to_item = {}

            for idx, item in enumerate(suggestions):
                display_name = item.get("display_name", "")
                if not display_name:
                    continue

                label = str(
                    item.get(
                        "label",
                        ""
                    )
                ).strip()

                if not label:
                    label = str(
                        display_name
                    ).strip()

                option = f"{idx + 1}. {label}"

                suggestion_options.append(option)
                option_to_display_name[option] = display_name
                option_to_item[option] = item

            if suggestion_options:
                selected_option = st.selectbox(
                    "Select the correct OSM place",
                    suggestion_options,
                    key="osm_selected_place_suggestion",
                    help=(
                        "For city-only searches, choose the matching city/county/state/country. "
                        "The selected dropdown value will be used when downloading OSM roads."
                    )
                )

                selected_place_for_download = option_to_display_name.get(
                    selected_option,
                    place_query
                )

                selected_place_info_for_download = option_to_item.get(
                    selected_option,
                    None
                )

                if selected_place_info_for_download is not None:
                    st.session_state[
                        "osm_selected_place_info"
                    ] = selected_place_info_for_download

                selected_clean_label = str(
                    selected_place_info_for_download.get("label", "")
                    if selected_place_info_for_download is not None
                    else ""
                ).strip()

                st.caption(
                    "Selected for download: "
                    + (selected_clean_label or str(selected_place_for_download))
                )

                if selected_place_info_for_download is not None:
                    selected_source = str(
                        selected_place_info_for_download.get("source", "OSM")
                    )

                    if selected_place_info_for_download.get("geojson"):
                        st.caption(
                            "This selected place includes a saved boundary polygon. "
                            "The Download OSM roads step will use that exact boundary."
                        )
                    elif selected_source.lower().startswith("photon"):
                        st.caption(
                            "The app will try to retrieve the exact OSM boundary "
                            "before downloading roads."
                        )

                if st.button(
                    "Use selected place name",
                    key="use_selected_osm_place"
                ):
                    st.session_state["osm_place_query"] = selected_place_for_download
                    st.session_state["osm_place_query_pending"] = selected_place_for_download

                    if selected_place_info_for_download is not None:
                        st.session_state[
                            "osm_selected_place_info"
                        ] = selected_place_info_for_download

                    st.session_state.pop(
                        "osm_place_suggestions",
                        None
                    )
                    st.rerun()

        network_type = st.selectbox(
            "OSM network type",
            [
                "drive",
                "drive_service"
            ],
            index=0,
            help=(
                "drive is usually best for corridor analysis. drive_service also includes "
                "service roads, which can then be mapped to 'Omit From Analysis'."
            ),
            key="osm_network_type"
        )

        if st.button(
            "Download OSM roads",
            key="download_osm_roads"
        ):

            try:
                with st.spinner(
                    "Downloading OSM roads for the selected place. "
                    "Larger cities can take a few minutes."
                ):
                    roads, selected_boundary = fetch_osm_roads_for_place(
                        selected_place_for_download,
                        network_type=network_type,
                        place_info=selected_place_info_for_download
                    )

                st.session_state["osm_raw_roads"] = roads
                st.session_state["selected_boundary"] = selected_boundary
                st.session_state["area_name"] = str(selected_place_for_download).strip()
                st.session_state["osm_place_query"] = str(selected_place_for_download).strip()

                for k in [
                    "base_roads",
                    "selected_roads",
                    "analysis_roads",
                    "analysis_road_filter_signature",
                    "analysis_road_class_col",
                    "analysis_road_class_values",
                    "roads_class_display",
                ]:
                    st.session_state.pop(k, None)

                _clear_downstream_results_after_road_change()

                st.success(
                    f"Downloaded {len(roads):,} OSM road edges. Review the highway mapping; "
                    "FromMile and ToMile will update automatically."
                )

            except Exception as e:
                st.error(
                    f"Unable to download OSM roads: {e}"
                )

        osm_raw_roads = st.session_state.get(
            "osm_raw_roads",
            None
        )

        selected_boundary = st.session_state.get(
            "selected_boundary",
            selected_boundary
        )

        if osm_raw_roads is not None and not osm_raw_roads.empty:

            st.caption(
                f"OSM road edges available for mapping: {len(osm_raw_roads):,}"
            )

            osm_mapping = _render_osm_highway_mapping(
                osm_raw_roads
            )

            mapped_roads_preview = apply_osm_highway_mapping(
                osm_raw_roads,
                osm_mapping
            )

            analysis_osm_roads_preview = mapped_roads_preview[
                mapped_roads_preview["RoadClass"] != "Omit From Analysis"
            ].copy()

            if analysis_osm_roads_preview.empty:
                st.warning(
                    "All OSM highway classes are currently mapped to 'Omit From Analysis'. "
                    "Change at least one class before generating roads."
                )
            else:
                st.session_state["show_roads_class_type"] = True
                st.session_state["road_class_legend_enabled"] = True

                st.caption(
                    "Preview after current OSM highway mapping. This preview updates when you change the mapping."
                )

                osm_preview_map = make_map(
                    boundary=selected_boundary,
                    roads=analysis_osm_roads_preview,
                    roads_class=analysis_osm_roads_preview
                )

                st_folium(
                    osm_preview_map,
                    width=1200,
                    height=650,
                    key="osm_roads_preview_map"
                )

            osm_milepost_signature = (
                len(osm_raw_roads),
                tuple(sorted((str(k), str(v)) for k, v in osm_mapping.items())),
            )

            if (
                st.session_state.get("osm_milepost_signature")
                != osm_milepost_signature
            ):
                mapped_roads = mapped_roads_preview.copy()

                omitted_count = int(
                    (mapped_roads["RoadClass"] == "Omit From Analysis").sum()
                )

                analysis_osm_roads = mapped_roads[
                    mapped_roads["RoadClass"] != "Omit From Analysis"
                ].copy()

                if analysis_osm_roads.empty:
                    st.warning(
                        "All OSM highway classes are mapped to 'Omit From Analysis'. Change at least one class before generating roads."
                    )
                else:
                    route_col = "RouteNameOSM"
                    segment_id_col = "OSMEdgeID"

                    base_roads = _generate_mileposts_for_road_source(
                        roads=analysis_osm_roads,
                        route_col=route_col,
                        segment_id_col=segment_id_col
                    )

                    base_roads = base_roads.to_crs(
                        4326
                    )

                    st.session_state["base_roads"] = base_roads
                    st.session_state["selected_roads"] = base_roads
                    st.session_state["selected_boundary"] = selected_boundary
                    st.session_state["route_col"] = route_col
                    st.session_state["segment_id_col"] = segment_id_col
                    st.session_state["osm_highway_mapping"] = osm_mapping

                    if "FunctionalClass" not in base_roads.columns and "RoadClass" in base_roads.columns:
                        base_roads["FunctionalClass"] = base_roads["RoadClass"]

                    class_col_for_filter = (
                        "FunctionalClass"
                        if "FunctionalClass" in base_roads.columns
                        else "RoadClass"
                    )

                    osm_classes = sorted(
                        base_roads[class_col_for_filter]
                        .dropna()
                        .astype(str)
                        .unique()
                    ) if class_col_for_filter in base_roads.columns else []

                    st.session_state["road_class_layer_enabled"] = True
                    st.session_state["road_class_legend_enabled"] = True
                    st.session_state["show_roads_class_type"] = True
                    st.session_state["road_class_viz_col"] = class_col_for_filter
                    st.session_state["road_class_viz_values"] = osm_classes

                    st.session_state.pop(
                        "analysis_roads",
                        None
                    )

                    st.session_state.pop(
                        "analysis_road_filter_signature",
                        None
                    )

                    _clear_downstream_results_after_road_change()

                    st.session_state["active_map_layer"] = "Roads"
                    st.session_state[
                        "osm_milepost_signature"
                    ] = osm_milepost_signature

                    st.success(
                        f"OSM mapping applied and FromMile / ToMile generated automatically "
                        f"for {len(base_roads):,} analysis road segments. "
                        f"Omitted OSM edges: {omitted_count:,}."
                    )

            else:
                base_roads = st.session_state.get("base_roads", base_roads)

    # =====================================================
    # Option C: Custom uploaded road network
    # =====================================================
    else:

        st.subheader("Upload custom road network")
        st.caption("Upload a zipped shapefile, shapefile components, GeoPackage, or GeoJSON.")

        st.info(
            "Upload shapefile components together "
            "(.shp, .dbf, .shx, .prj)."
        )

        custom_road_files = st.file_uploader(
            "Upload road ZIP / components / GPKG / GeoJSON",
            type=[
                "zip",
                "gpkg",
                "geojson",
                "json",
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

            except Exception as e:

                st.error(
                    "Unable to read the road upload. See the full error below."
                )
                st.exception(e)

                st.stop()

            if roads.crs is None:

                st.error(
                    "Uploaded road file has no CRS. "
                    "Please define CRS first."
                )

                st.stop()

            roads = roads.to_crs(
                4326
            )

            st.success(
                "Custom road network loaded."
            )

            area_name = st.text_input(
                "Enter study area name",
                value="Custom Road Network"
            )

            st.session_state[
                "area_name"
            ] = area_name

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

            custom_milepost_signature = (
                tuple(
                    (
                        getattr(upload, "name", ""),
                        getattr(upload, "size", None),
                    )
                    for upload in custom_road_files
                ),
                str(route_col),
                str(segment_id_col),
            )

            if (
                st.session_state.get("custom_milepost_signature")
                != custom_milepost_signature
            ):
                base_roads = _generate_mileposts_for_road_source(
                    roads=roads,
                    route_col=route_col,
                    segment_id_col=segment_id_col
                )

                base_roads = base_roads.to_crs(
                    4326
                )

                selected_boundary = gpd.GeoDataFrame(
                    geometry=[
                        base_roads.geometry.union_all().convex_hull
                    ],
                    crs=base_roads.crs
                )

                st.session_state[
                    "base_roads"
                ] = base_roads

                st.session_state[
                    "selected_roads"
                ] = base_roads

                st.session_state[
                    "selected_boundary"
                ] = selected_boundary

                st.session_state[
                    "route_col"
                ] = route_col

                st.session_state[
                    "segment_id_col"
                ] = segment_id_col

                st.session_state.pop(
                    "analysis_roads",
                    None
                )

                st.session_state.pop(
                    "analysis_road_filter_signature",
                    None
                )

                _clear_downstream_results_after_road_change()

                st.session_state[
                    "active_map_layer"
                ] = "Roads"

                st.session_state[
                    "custom_milepost_signature"
                ] = custom_milepost_signature

                st.success(
                    "Road data loaded. FromMile and ToMile were generated automatically."
                )

            else:
                base_roads = st.session_state.get("base_roads", base_roads)

    if base_roads is None:

        base_roads = st.session_state.get(
            "base_roads",
            st.session_state.get(
                "selected_roads",
                None
            )
        )

    if selected_boundary is None:

        selected_boundary = st.session_state.get(
            "selected_boundary",
            None
        )

    if base_roads is not None:

        base_roads = base_roads.copy()

        if "RoadClass" in base_roads.columns:
            base_roads["RoadClass"] = (
                base_roads["RoadClass"]
                .fillna("Unknown")
            )

            if "FunctionalClass" not in base_roads.columns:
                base_roads["FunctionalClass"] = base_roads["RoadClass"]

        if "FunctionalClass" in base_roads.columns:
            base_roads["FunctionalClass"] = (
                base_roads["FunctionalClass"]
                .fillna("Unknown")
            )

        if "RoadType" in base_roads.columns:
            base_roads["RoadType"] = (
                base_roads["RoadType"]
                .fillna("Unknown")
            )

        roads_class_display = (
            _apply_road_network_filter(
                base_roads
            )
        )

        filter_is_on = bool(
            st.session_state.get(
                "road_class_layer_enabled",
                False
            )
        )

        if filter_is_on:
            analysis_roads = st.session_state.get(
                "analysis_roads",
                base_roads.iloc[0:0].copy()
            )
        else:
            analysis_roads = base_roads

        if analysis_roads is None:
            analysis_roads = base_roads.iloc[0:0].copy()

        st.session_state[
            "selected_boundary"
        ] = selected_boundary

        st.session_state[
            "base_roads"
        ] = base_roads

        st.session_state[
            "selected_roads"
        ] = analysis_roads

        st.write(
            f"Analysis roads: {len(analysis_roads)}"
        )

        st.caption(
            f"Base roads before filter: {len(base_roads)}"
        )

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
            "FunctionalClass",
            "RoadClass",
            "RoadType",
            "RTTYP",
            "MTFCC",
            st.session_state.get("analysis_road_class_col")
        ]

        road_table_cols = []

        for c in raw_road_table_cols:
            if (
                c is not None
                and c in analysis_roads.columns
                and c not in road_table_cols
            ):
                road_table_cols.append(c)

        with st.expander(
            "Analysis road attributes",
            expanded=False
        ):

            if road_table_cols:
                st.dataframe(
                    analysis_roads[
                        road_table_cols
                    ].drop_duplicates(),
                    width="stretch"
                )
            else:
                st.info(
                    "No displayable road attribute columns found."
                )


        fmap = make_map(
            boundary=selected_boundary,
            roads=analysis_roads,
            roads_class=roads_class_display
        )

        st_folium(
            fmap,
            width=1200,
            height=900,
            key="road_map"
        )

        if st.session_state.get(
            "show_roads_class_type",
            False
        ):
            st.session_state[
                "show_roads_class_type"
            ] = False
