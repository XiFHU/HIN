"""Crash classification and spatial-unit creation UI."""


def render_classification_step(workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    selected_roads = st.session_state.get("selected_roads", None)
    signals_clean = st.session_state.get("signals_clean", None)
    corridors = st.session_state.get("corridors", None)
    crashes = st.session_state.get("crashes", None)

    if spatial_unit == "Intersection":
        st.markdown(
            '<div class="section-title">Signalized Intersection Crash Classification</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="section-title">Classification / Spatial Units</div>',
            unsafe_allow_html=True,
        )

    from modules.crash_classification import (
        create_intersection_units,
        create_corridor_units,
        create_road_segment_units,
        assign_crashes_to_units,
        summarize_kabco,
    )

    if crashes is None:
        st.info("Upload crash data first.")
        return

    crash_analysis_type = {
        "Intersection": "Signalized intersection crashes",
        "Corridor": "Corridor crashes",
        "Segment": "Road segment crashes",
    }[spatial_unit]

    st.info(f"Current spatial unit: {crash_analysis_type}")

    if crash_analysis_type == "Signalized intersection crashes":
        if selected_roads is None:
            st.warning("Upload/select roads first.")
            return

        if signals_clean is None or signals_clean.empty:
            st.warning("Generate OSM traffic signals first. Signalized intersection locations are based on cleaned OSM signals.")
            return

        intersection_buffer_ft = st.number_input(
            "Signalized intersection buffer size, feet",
            min_value=25,
            max_value=1000,
            value=250,
            step=25,
            key="classification_signalized_intersection_buffer_ft",
        )

        st.caption(
            "This analysis treats cleaned OSM traffic signal points as signalized intersection locations. "
            "Non-signalized intersections are not generated or classified in this version."
        )

        if st.button("Classify Signalized Intersection Crashes", key="classify_signalized_intersection_crashes"):
            with st.spinner("Creating signalized intersection buffers and assigning crashes..."):
                spatial_units = create_intersection_units(
                    signals_clean,
                    buffer_ft=intersection_buffer_ft,
                )

                # Make the output labeling explicit so tables/maps do not imply all intersections.
                spatial_units["UnitType"] = "Signalized Intersection"
                if "IntersectionType" not in spatial_units.columns:
                    spatial_units["IntersectionType"] = "Signalized"

                assigned_crashes = assign_crashes_to_units(
                    crashes,
                    spatial_units,
                    unit_id_col="UnitID",
                    method="within",
                )

                kabco_result = summarize_kabco(
                    assigned_crashes,
                    unit_id_col="UnitID",
                )

                st.session_state["spatial_units"] = spatial_units
                st.session_state["assigned_crashes"] = assigned_crashes
                st.session_state["kabco_result"] = kabco_result
                st.session_state["analysis_type"] = "Signalized Intersection"
                st.session_state["intersection_source"] = "OSM Signals"

                st.session_state["active_map_layer"] = (
                    "Crash Density Spatial Units"
                )

            st.success(
                f"Signalized intersection crashes classified for {len(spatial_units):,} signalized intersection units."
            )

    elif crash_analysis_type == "Corridor crashes":
        if corridors is None:
            st.warning("Build corridors first.")
            return

        if st.button("Classify Corridor Crashes", key="classify_corridor_crashes"):
            spatial_units = create_corridor_units(corridors)

            assigned_crashes = assign_crashes_to_units(
                crashes,
                spatial_units,
                unit_id_col="UnitID",
                method="within",
            )

            kabco_result = summarize_kabco(
                assigned_crashes,
                unit_id_col="UnitID",
            )

            st.session_state["spatial_units"] = spatial_units
            st.session_state["assigned_crashes"] = assigned_crashes
            st.session_state["kabco_result"] = kabco_result
            st.session_state["analysis_type"] = "Corridor"
            st.success("Corridor crashes classified.")

            st.session_state["active_map_layer"] = (
                "Crash Density Spatial Units"
            )


    elif crash_analysis_type == "Road segment crashes":
        segment_unit_method = st.radio(
            "Road segment unit method",
            [
                "Use uploaded road segments",
                "Create equal-length segments"

            ],
            horizontal=True,
            key="classification_segment_unit_method",
        )

        segment_search_distance_ft = st.number_input(
            "Maximum crash distance from segment, feet",
            min_value=10,
            max_value=500,
            value=100,
            step=10,
            key="classification_segment_search_distance_ft",
        )

        if selected_roads is None:
            st.warning("Select roads first.")
            return

        if segment_unit_method == "Create equal-length segments":
            segment_length_ft = st.number_input(
                "Road segment length, feet",
                min_value=50,
                max_value=5280,
                value=500,
                step=50,
                key="classification_segment_length_ft",
            )

            if st.button("Classify Road Segment Crashes", key="classify_equal_segment_crashes"):
                spatial_units = create_road_segment_units(
                    selected_roads,
                    segment_length_ft=segment_length_ft,
                )

                assigned_crashes = assign_crashes_to_units(
                    crashes,
                    spatial_units,
                    unit_id_col="UnitID",
                    method="nearest",
                    search_distance_ft=segment_search_distance_ft,
                )

                kabco_result = summarize_kabco(
                    assigned_crashes,
                    unit_id_col="UnitID",
                )

                st.session_state["spatial_units"] = spatial_units
                st.session_state["assigned_crashes"] = assigned_crashes
                st.session_state["kabco_result"] = kabco_result
                st.session_state["analysis_type"] = "Road Segment"
                st.session_state["segment_unit_method"] = "Equal Length"

                st.session_state["active_map_layer"] = (
                    "Crash Density Spatial Units"
                )
           
                st.success("Road segment crashes classified.")

        elif segment_unit_method == "Use uploaded road segments":
            if st.button("Classify Uploaded Road Segment Crashes", key="classify_uploaded_segment_crashes"):
                spatial_units = selected_roads.copy()

                # TIGER LINEARID and some uploaded road ID fields are not always
                # unique after clipping, exploding, or city selection.  Use a
                # guaranteed unique internal UnitID for crash assignment, and
                # keep the original segment ID in SegmentID/SourceSegmentID for
                # tables, popups, and export.  This prevents TIGER segment crash
                # density maps from becoming empty or unstable after the join.
                spatial_units = spatial_units[
                    spatial_units.geometry.notna()
                ].copy()
                spatial_units = spatial_units[
                    ~spatial_units.geometry.is_empty
                ].copy()

                try:
                    spatial_units["geometry"] = spatial_units.geometry.make_valid()
                    spatial_units = spatial_units.explode(
                        index_parts=False,
                        ignore_index=True,
                    )
                except Exception:
                    spatial_units = spatial_units.reset_index(drop=True)

                spatial_units = spatial_units[
                    spatial_units.geometry.geom_type.isin(
                        ["LineString", "MultiLineString"]
                    )
                ].copy()

                if spatial_units.empty:
                    st.error(
                        "No valid line road segments are available for crash-density classification."
                    )
                    st.stop()

                segment_id_col = st.session_state.get("segment_id_col", None)

                if segment_id_col is not None and segment_id_col in spatial_units.columns:
                    spatial_units["SourceSegmentID"] = spatial_units[
                        segment_id_col
                    ].astype(str)
                else:
                    spatial_units["SourceSegmentID"] = (
                        spatial_units.index + 1
                    ).astype(str)

                spatial_units = spatial_units.reset_index(drop=True)
                spatial_units["UnitID"] = [
                    f"SEGROW_{i + 1}" for i in range(len(spatial_units))
                ]
                spatial_units["UnitType"] = "Road Segment"
                spatial_units["SegmentID"] = spatial_units["SourceSegmentID"]

                assigned_crashes = assign_crashes_to_units(
                    crashes,
                    spatial_units,
                    unit_id_col="UnitID",
                    method="nearest",
                    search_distance_ft=segment_search_distance_ft,
                )

                kabco_result = summarize_kabco(
                    assigned_crashes,
                    unit_id_col="UnitID",
                )

                st.session_state["spatial_units"] = spatial_units
                st.session_state["assigned_crashes"] = assigned_crashes
                st.session_state["kabco_result"] = kabco_result
                st.session_state["analysis_type"] = "Uploaded Road Segment"
                st.session_state["segment_unit_method"] = "Uploaded Road Segments"

                st.session_state["active_map_layer"] = (
                    "Crash Density Spatial Units"
                )

                st.success("Uploaded road segment crashes classified.")
