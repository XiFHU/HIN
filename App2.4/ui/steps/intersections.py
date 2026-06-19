"""Road-network intersection generation UI."""


def render_intersections_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    if spatial_unit != "Intersection":
        return

    selected_roads = st.session_state.get("selected_roads", None)
    selected_boundary = st.session_state.get("selected_boundary", None)
    signals_clean = st.session_state.get("signals_clean", None)
    intersections = st.session_state.get("intersections", None)

    st.markdown('<div class="section-title">Intersection Locations</div>', unsafe_allow_html=True)

    if selected_roads is None:
        st.info("Upload/select roads first.")
        return

    st.caption(
        "Generate intersections from road geometry, then classify each one as "
        "Signalized or Non-signalized using OSM signals."
    )

    cluster_tolerance_ft = st.number_input(
        "Merge nearby intersection points, feet",
        min_value=10,
        max_value=250,
        value=int(st.session_state.get("intersection_cluster_tolerance_ft", 50)),
        step=10,
        key="intersection_step_cluster_tolerance_ft",
    )

    signal_match_distance_ft = st.number_input(
        "Signal match distance, feet",
        min_value=25,
        max_value=500,
        value=int(st.session_state.get("intersection_signal_match_distance_ft", 100)),
        step=25,
        key="intersection_step_signal_match_distance_ft",
    )

    if signals_clean is None:
        st.warning(
            "OSM signals have not been generated yet. You can still generate road intersections, "
            "but all intersections will be labeled Non-signalized until signals are available."
        )

    if st.button("Generate Intersection Locations", key="generate_intersection_locations"):
        from modules.intersections import generate_road_intersections

        with st.spinner("Generating road-network intersections and matching OSM signals..."):
            intersections = generate_road_intersections(
                selected_roads,
                signals=signals_clean,
                route_col=st.session_state.get("route_col", "FULLNAME"),
                segment_id_col=st.session_state.get("segment_id_col", None),
                cluster_tolerance_ft=cluster_tolerance_ft,
                signal_match_distance_ft=signal_match_distance_ft,
            )

            st.session_state["intersections"] = intersections
            st.session_state["intersection_cluster_tolerance_ft"] = cluster_tolerance_ft
            st.session_state["intersection_signal_match_distance_ft"] = signal_match_distance_ft

        signalized_count = 0
        nonsignalized_count = 0

        if intersections is not None and not intersections.empty:
            signalized_count = int((intersections["IntersectionControl"] == "Signalized").sum())
            nonsignalized_count = int((intersections["IntersectionControl"] == "Non-signalized").sum())

        st.success(
            f"Generated {len(intersections):,} intersections: "
            f"{signalized_count:,} signalized, {nonsignalized_count:,} non-signalized."
        )

    if intersections is not None and not intersections.empty:
        signalized_count = int((intersections["IntersectionControl"] == "Signalized").sum())
        nonsignalized_count = int((intersections["IntersectionControl"] == "Non-signalized").sum())

        st.info(
            f"Current intersections: {len(intersections):,} total | "
            f"{signalized_count:,} signalized | {nonsignalized_count:,} non-signalized"
        )

        display_option = st.radio(
            "Show intersection locations",
            [
                "All intersections",
                "Signalized only",
                "Non-signalized only",
            ],
            horizontal=True,
            key="intersection_location_display_option",
        )

        intersections_for_map = intersections.copy()
        if display_option == "Signalized only":
            intersections_for_map = intersections_for_map[
                intersections_for_map["IntersectionControl"] == "Signalized"
            ].copy()
        elif display_option == "Non-signalized only":
            intersections_for_map = intersections_for_map[
                intersections_for_map["IntersectionControl"] == "Non-signalized"
            ].copy()

        with st.expander("Intersection location table", expanded=False):
            table = intersections_for_map.copy()
            table["Latitude"] = table.geometry.y
            table["Longitude"] = table.geometry.x
            display_cols = [
                c for c in [
                    "IntersectionID",
                    "IntersectionControl",
                    "IsSignalized",
                    "RoadName1",
                    "RoadName2",
                    "RoadNames",
                    "SignalCnt",
                    "SignalIDs",
                    "Latitude",
                    "Longitude",
                ] if c in table.columns
            ]
            st.dataframe(table[display_cols], width="stretch")


        fmap = make_map(
            boundary=selected_boundary,
            roads=selected_roads,
            signals=signals_clean,
            intersections=intersections_for_map,
        )

        st_folium(
            fmap,
            width=1200,
            height=900,
            key=(
                "intersection_locations_map_"
                + str(display_option)
                + "_"
                + str(len(intersections_for_map))
            ),
        )
