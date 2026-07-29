"""Step 3 corridor building UI."""

from modules.defaults import CORRIDOR_DEFAULTS


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

    final_corridors = st.session_state.get(
        "final_corridors",
        corridors
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

            min_signals_for_corridor = CORRIDOR_DEFAULTS["min_signals_for_corridor"]
            nearest_road_distance_ft = CORRIDOR_DEFAULTS["nearest_road_distance_ft"]
            corridor_width_ft = CORRIDOR_DEFAULTS["corridor_width_ft"]
            corridor_search_buffer_ft = CORRIDOR_DEFAULTS["corridor_search_buffer_ft"]

            with st.expander("Optional corridor settings", expanded=False):
                customize_corridor_settings = st.checkbox(
                    "Customize corridor thresholds",
                    value=False,
                    key="customize_corridor_thresholds"
                )

                if customize_corridor_settings:
                    min_signals_for_corridor = st.number_input(
                        "Minimum signals required to create a corridor",
                        min_value=1,
                        max_value=20,
                        value=CORRIDOR_DEFAULTS["min_signals_for_corridor"],
                        step=1,
                        key="corridor_min_signals_optional"
                    )

                    nearest_road_distance_ft = st.number_input(
                        "Maximum signal distance from named road (feet)",
                        min_value=25,
                        max_value=1000,
                        value=CORRIDOR_DEFAULTS["nearest_road_distance_ft"],
                        step=25,
                        key="corridor_nearest_road_distance_ft_optional",
                        help=(
                            "Signals farther than this from a named road are not assigned to that road. "
                            "The app uses this feet value for geometry calculations."
                        )
                    )

                    corridor_width_ft = st.number_input(
                        "Corridor width (feet)",
                        min_value=10,
                        max_value=300,
                        value=CORRIDOR_DEFAULTS["corridor_width_ft"],
                        step=5,
                        key="corridor_width_ft_optional",
                        help=(
                            "Width of the corridor polygon around the selected road geometry. "
                            "The app uses this feet value for corridor geometry."
                        )
                    )

                    corridor_search_buffer_ft = st.number_input(
                        "Fallback road search buffer around signals (feet)",
                        min_value=25,
                        max_value=1000,
                        value=CORRIDOR_DEFAULTS["corridor_search_buffer_ft"],
                        step=25,
                        key="corridor_search_buffer_ft_optional",
                        help=(
                            "Backup search distance used only when route-name matching cannot find enough road geometry. "
                            "Because road-name normalization is already used, keep this conservative to avoid pulling in nearby side streets."
                        )
                    )
                else:
                    st.caption(
                        "Using defaults: "
                        f"min signals {min_signals_for_corridor}; "
                        f"road match {nearest_road_distance_ft} ft; "
                        f"corridor width {corridor_width_ft} ft; "
                        f"fallback buffer {corridor_search_buffer_ft} ft."
                    )

            nearest_road_distance_m = (
                float(nearest_road_distance_ft) * 0.3048
            )
            corridor_width_m = (
                float(corridor_width_ft) * 0.3048
            )
            corridor_search_buffer_m = (
                float(corridor_search_buffer_ft) * 0.3048
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
                        "final_corridors"
                    ] = corridors.copy()

                    st.session_state[
                        "dropped_corridor_ids"
                    ] = []

                    st.session_state[
                        "applied_dropped_corridor_ids"
                    ] = []

                    st.session_state[
                        "corridor_roads"
                    ] = corridor_roads

                    st.session_state.pop(
                        "spatial_units",
                        None
                    )

                    st.session_state.pop(
                        "spatial_units_density_map",
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
            "Return to Road data source and finish loading the road network before building corridors."
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


    # Corridor Signal Summary table is intentionally hidden.
    # The detailed Signals With CorridorID table remains available above.


    if corridors is not None:

        st.subheader("Review / Drop Corridors")

        if corridors.empty:

            final_corridors = corridors.copy()
            st.session_state["final_corridors"] = final_corridors
            st.info("No corridors are available to review.")

        elif "CorridorID" not in corridors.columns:

            final_corridors = corridors.copy()
            st.session_state["final_corridors"] = final_corridors
            st.warning(
                "CorridorID was not found, so corridors cannot be dropped by ID."
            )

        else:

            corridor_id_options = sorted(
                corridors["CorridorID"]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            )

            previous_applied_drop_ids = set(
                st.session_state.get(
                    "applied_dropped_corridor_ids",
                    []
                )
            )

            default_drop_ids = [
                corridor_id
                for corridor_id in st.session_state.get(
                    "dropped_corridor_ids",
                    []
                )
                if corridor_id in corridor_id_options
            ]

            drop_corridor_ids = st.multiselect(
                "Drop corridors by CorridorID before segmentation/results",
                options=corridor_id_options,
                default=default_drop_ids,
                key="corridors_drop_by_id_select",
                help=(
                    "Dropped corridors are removed from the final corridor layer. "
                    "Corridor crash classification, road segmentation, and sliding-window HIN analysis "
                    "will use only the remaining final corridors."
                )
            )

            current_drop_ids = set(drop_corridor_ids)

            final_corridors = corridors[
                ~corridors["CorridorID"].astype(str).isin(
                    current_drop_ids
                )
            ].copy()

            st.session_state["dropped_corridor_ids"] = list(
                drop_corridor_ids
            )
            st.session_state["final_corridors"] = final_corridors

            if current_drop_ids != previous_applied_drop_ids:

                st.session_state[
                    "applied_dropped_corridor_ids"
                ] = list(drop_corridor_ids)

                for stale_key in [
                    "spatial_units",
                    "spatial_units_density_map",
                    "assigned_crashes",
                    "kabco_result",
                    "section7_results",
                    "section7_original_density",
                    "section7_crashes_for_map"
                ]:
                    st.session_state.pop(stale_key, None)

                st.session_state[
                    "active_map_layer"
                ] = "Corridors"

                if drop_corridor_ids:
                    st.info(
                        "Corridor drop list changed. Downstream crash classification, "
                        "density, and sliding-window results were cleared so they can be rebuilt "
                        "from the final corridors."
                    )

            st.write(
                f"Original corridors: {len(corridors):,} | "
                f"Dropped: {len(drop_corridor_ids):,} | "
                f"Final corridors: {len(final_corridors):,}"
            )

            if final_corridors.empty:
                st.warning(
                    "All corridors are currently dropped. Keep at least one corridor before running segmentation or crash analysis."
                )

            with st.expander(
                "View final corridors table",
                expanded=False
            ):
                st.dataframe(
                    final_corridors.drop(
                        columns="geometry",
                        errors="ignore"
                    ),
                    width="stretch"
                )

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
                corridors=final_corridors
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
                        final_corridors,
                        "final_corridors"
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
                    f"Could not create Final Corridor Shapefile ZIP: {e}"
                )

        if "corridor_shp_bytes" in st.session_state:

            st.download_button(
                "Download Final Corridor Shapefile ZIP",
                st.session_state[
                    "corridor_shp_bytes"
                ],
                file_name="final_corridors_shapefile.zip",
                mime="application/zip",
                key="download_corridor_shp"
            )
