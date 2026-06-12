"""Step 3 corridor building UI."""


def render_corridors_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    selected_roads = st.session_state.get("selected_roads", None)
    selected_boundary = st.session_state.get("selected_boundary", None)
    signals_clean = st.session_state.get("signals_clean", None)

    # -----------------------------
    # 3. Advanced: Build corridors
    # -----------------------------

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
