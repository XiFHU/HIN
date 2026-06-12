"""Step 2 OSM signal generation UI."""


def render_signals_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    selected_roads = st.session_state.get("selected_roads", None)
    roads_class_display = st.session_state.get("roads_class_display", None)
    selected_boundary = st.session_state.get("selected_boundary", None)
    city_name = st.session_state.get("area_name", "Study Area")

    # -----------------------------
    # 2. Generate OSM signals
    # -----------------------------

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

                st.session_state[
                    "active_map_layer"
                ] = "Signals"

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
            roads_class=roads_class_display,
            signals=signals_clean
        )

        st_folium(
            fmap,
            width=1200,
            height=900,
            key="signal_map"
        )
