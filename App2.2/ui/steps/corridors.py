"""Step 3 corridor building UI."""


def render_corridors_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    selected_roads = st.session_state.get(
        "selected_roads",
        None
    )

    base_roads = st.session_state.get(
        "base_roads",
        selected_roads
    )

    roads_class_display = st.session_state.get(
        "roads_class_display",
        None
    )

    selected_boundary = st.session_state.get(
        "selected_boundary",
        None
    )

    signals_clean = st.session_state.get(
        "signals_clean",
        None
    )

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

    corridor_roads = st.session_state.get(
        "corridor_roads",
        selected_roads
    )

    if selected_roads is not None and signals_clean is not None:

        st.subheader("Corridor Road Network")

        corridor_roads = selected_roads.copy()

        use_corridor_road_filter = st.checkbox(
            "Filter road classes used to build corridors",
            value=False,
            key="use_corridor_road_filter"
        )

        # Default corridor geometry to the Step 1 analysis road filter.
        # The optional corridor-specific filter below can override this.
        if st.session_state.get("road_class_layer_enabled", False):
            road_class_col_for_corridors = st.session_state.get(
                "analysis_road_class_col",
                None
            )
            selected_road_classes_for_corridors = st.session_state.get(
                "analysis_road_class_values",
                None
            )
        else:
            road_class_col_for_corridors = None
            selected_road_classes_for_corridors = None

        if use_corridor_road_filter:

            road_class_cols = [
                c for c in base_roads.columns
                if c != "geometry"
            ]

            if road_class_cols:

                default_col = st.session_state.get(
                    "analysis_road_class_col",
                    road_class_cols[0]
                )

                default_index = (
                    road_class_cols.index(default_col)
                    if default_col in road_class_cols
                    else 0
                )

                corridor_road_class_col = st.selectbox(
                    "Road class column for corridor building",
                    road_class_cols,
                    index=default_index,
                    key="corridor_road_class_col"
                )

                corridor_road_values = sorted(
                    base_roads[
                        corridor_road_class_col
                    ]
                    .dropna()
                    .astype(str)
                    .unique()
                )

                default_corridor_values = st.session_state.get(
                    "analysis_road_class_values",
                    corridor_road_values
                )

                default_corridor_values = [
                    v for v in default_corridor_values
                    if v in corridor_road_values
                ]

                selected_corridor_road_values = st.multiselect(
                    "Road classes to use for corridor building",
                    corridor_road_values,
                    default=default_corridor_values,
                    key="corridor_road_class_values"
                )

                road_class_col_for_corridors = (
                    corridor_road_class_col
                )

                selected_road_classes_for_corridors = (
                    selected_corridor_road_values
                )

                corridor_roads = base_roads[
                    base_roads[
                        corridor_road_class_col
                    ]
                    .astype(str)
                    .isin(selected_corridor_road_values)
                ].copy()

                st.write(
                    "Corridor road class column:",
                    corridor_road_class_col
                )

                st.dataframe(
                    corridor_roads[
                        [corridor_road_class_col]
                    ]
                    .value_counts()
                    .reset_index()
                    .head(30),
                    width="stretch"
                )

            else:

                st.warning(
                    "No road attribute columns are available for corridor filtering."
                )

        st.write(
            f"Roads used for corridor building: {len(corridor_roads)}"
        )

        if corridor_roads.empty:

            st.error(
                "No roads are available for corridor building. "
                "Check the selected road classes."
            )

        else:

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
                max_value=300,
                value=100,
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
                "Fallback road search buffer around signals, meters",
                min_value=25,
                max_value=500,
                value=200,
                step=25,
                help=(
                    "Used only when the route name cannot be found in the corridor road layer. "
                    "Signal-to-road matching uses the setting above."
                )
            )

            if st.button(
                "Build Corridors",
                key="build_corridors_button"
            ):

                with st.spinner(
                    "Assigning CorridorID and building corridor polygons..."
                ):

                    route_col = st.session_state.get(
                        "route_col",
                        "FULLNAME"
                    )

                    if route_col not in base_roads.columns:
                        st.error(
                            f"Route column '{route_col}' is not in the base road layer."
                        )
                        st.stop()

                    signals_with_corridor = (
                        assign_corridor_ids_to_signals(
                            signals_clean,
                            base_roads,
                            city_name=area_name,
                            county_name="",
                            min_signals=min_signals_for_corridor,
                            max_distance_m=nearest_road_distance_m,
                            road_name_col=route_col
                        )
                    )

                    if (
                        "IsValidCorridorSignal"
                        in signals_with_corridor.columns
                    ):
                        signals_for_corridors = (
                            signals_with_corridor[
                                signals_with_corridor[
                                    "IsValidCorridorSignal"
                                ] == True
                            ]
                            .copy()
                        )
                    else:
                        signals_for_corridors = (
                            signals_with_corridor
                            .copy()
                        )

                    corridor_summary = (
                        corridor_signal_summary(
                            signals_for_corridors
                        )
                    )

                    corridors = build_corridors(
                        roads=base_roads,
                        signals_with_corridor=signals_for_corridors,
                        corridor_width_m=corridor_width_m,
                        corridor_search_buffer_m=corridor_search_buffer_m,
                        signal_route_search_distance_m=nearest_road_distance_m,
                        min_signals=min_signals_for_corridor,
                        city_name=area_name,
                        route_col=route_col,
                        use_uploaded_road_names_for_signals=False,
                        road_class_col=road_class_col_for_corridors,
                        selected_road_classes=selected_road_classes_for_corridors,
                        export_debug_csv=True
                    )

                    st.session_state[
                        "signals_with_corridor"
                    ] = signals_with_corridor

                    st.session_state[
                        "signals_for_corridors"
                    ] = signals_for_corridors

                    st.session_state[
                        "corridor_signal_summary"
                    ] = corridor_summary

                    st.session_state[
                        "corridors"
                    ] = corridors

                    st.session_state[
                        "corridor_roads"
                    ] = corridor_roads

                    st.session_state.pop(
                        "spatial_units",
                        None
                    )

                    st.session_state.pop(
                        "assigned_crashes",
                        None
                    )

                    st.session_state.pop(
                        "kabco_result",
                        None
                    )

                    st.session_state.pop(
                        "section7_results",
                        None
                    )

                    st.session_state[
                        "active_map_layer"
                    ] = "Corridors"

                st.success(
                    f"Corridors built: {len(corridors)}"
                )

    elif selected_roads is None:

        st.info(
            "Generate FromMile and ToMile before building corridors."
        )

    elif signals_clean is None:

        st.info(
            "Generate signals before building corridors."
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
                "IsValidCorridorSignal",
                "Route",
                "Route_Normalized",
                "DistRoad",
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

            corridor_roads_for_map = st.session_state.get(
                "corridor_roads",
                corridor_roads
            )

            signals_for_map = signals_with_corridor

            if (
                signals_for_map is None
                or signals_for_map.empty
            ):
                signals_for_map = signals_clean

            fmap = make_map(
                boundary=selected_boundary,
                roads=corridor_roads_for_map,
                roads_class=None,
                signals=signals_for_map,
                corridors=corridors
            )

            st_folium(
                fmap,
                width=1200,
                height=900,
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
