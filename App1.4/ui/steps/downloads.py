"""Step 6 map and download controls for classified crash results."""


def render_results_downloads(
    st_folium,
    workflow_context,
    spatial_units_map,
    units_table,
    assigned_table,
    assigned_crashes,
    kabco_result,
    analysis_type,
    density_cmap,
):
    globals().update(workflow_context)

    selected_boundary = st.session_state.get("selected_boundary", None)
    selected_roads = st.session_state.get("selected_roads", None)
    roads_class_display = st.session_state.get("roads_class_display", None)
    signals_clean = st.session_state.get("signals_clean", None)

    if kabco_result is not None:
        st.download_button(
            "Download Crash Summary CSV",
            kabco_result.to_csv(index=False),
            file_name="crash_summary.csv",
            mime="text/csv",
            key=f"download_summary_{analysis_type}",
        )

    st.download_button(
        "Download Spatial Units CSV",
        units_table.to_csv(index=False),
        file_name="spatial_units.csv",
        mime="text/csv",
        key=f"download_units_csv_{analysis_type}",
    )

    st.download_button(
        "Download Assigned Crashes CSV",
        assigned_table.to_csv(index=False),
        file_name="assigned_crashes.csv",
        mime="text/csv",
        key=f"download_assigned_csv_{analysis_type}",
    )

    st.subheader("Download Original Crash Density GeoJSON")

    geojson_key = f"units_with_density_geojson_{analysis_type}"

    if st.button(
        "Prepare Original Crash Density GeoJSON",
        key=f"prepare_{geojson_key}",
    ):
        try:
            geojson_gdf = make_json_safe_gdf(spatial_units_map.to_crs(4326))
            geojson_bytes = geojson_gdf.to_json().encode("utf-8")
            st.session_state[geojson_key] = geojson_bytes
            st.success("Original crash density GeoJSON ready.")
        except Exception as e:
            st.error(f"Could not create spatial units GeoJSON: {e}")

    if geojson_key in st.session_state:
        st.download_button(
            "Download Original Crash Density GeoJSON",
            st.session_state[geojson_key],
            file_name="spatial_units_with_crash_density.geojson",
            mime="application/geo+json",
            key=f"download_{geojson_key}",
        )


    unit_display_option = st.radio(
        "Spatial unit display option",
        [
            "Show crashes with all spatial units",
            "Show crashes with spatial units that have crashes only",
        ],
        index=0,
        key=f"unit_display_option_{analysis_type}",
    )

    if unit_display_option == "Show crashes with spatial units that have crashes only":
        spatial_units_map_for_display = spatial_units_map[
            spatial_units_map["CrashCount"] > 0
        ].copy()
    else:
        spatial_units_map_for_display = spatial_units_map.copy()

    intersection_display_option = "Signalized intersections"

    display_unit_ids = set()
    if (
        spatial_units_map_for_display is not None
        and not spatial_units_map_for_display.empty
        and "UnitID" in spatial_units_map_for_display.columns
    ):
        display_unit_ids = set(spatial_units_map_for_display["UnitID"].astype(str))

    assigned_crashes_for_display = assigned_crashes
    if display_unit_ids and "UnitID" in assigned_crashes.columns:
        assigned_crashes_for_display = assigned_crashes[
            assigned_crashes["UnitID"].astype(str).isin(display_unit_ids)
        ].copy()

    if unit_display_option == "Show crashes with spatial units that have crashes only":
        signals_for_display = filter_points_to_units(
            signals_clean,
            spatial_units_map_for_display,
            buffer_m=20,
        )
    else:
        signals_for_display = signals_clean

    st.markdown("### Map layers")

    map_layer_options = [
        "Boundary",
        "Roads",
        "Signals",
        "Crash Density Spatial Units",
        "Assigned Crashes",
    ]

    selected_map_layers = st.multiselect(
        "Select layers to show on the crash assignment map",
        map_layer_options,
        default=[
            "Boundary",
            "Roads",
            "Signals",
            "Crash Density Spatial Units",
            "Assigned Crashes",
        ],
        key=f"selected_map_layers_{analysis_type}",
    )

    boundary_layer = selected_boundary if "Boundary" in selected_map_layers else None
    roads_layer = selected_roads if "Roads" in selected_map_layers else None
    signals_layer = signals_for_display if "Signals" in selected_map_layers else None
    spatial_units_layer = (
        spatial_units_map_for_display
        if "Crash Density Spatial Units" in selected_map_layers
        else None
    )
    crashes_layer = assigned_crashes_for_display if "Assigned Crashes" in selected_map_layers else None

    fmap = make_map(
        boundary=boundary_layer,
        roads=roads_layer,
        roads_class=st.session_state.get("roads_class_display", None) if roads_layer is not None else None,
        signals=signals_layer,
        corridors=None,
        spatial_units=spatial_units_layer,
        crashes=crashes_layer,
        density_cmap=density_cmap,
    )

    if spatial_units_layer is not None:
        density_cmap.add_to(fmap)

    fmap = add_map_elements(fmap)

    st.caption(
        "Only two GeoJSON exports are available in the app: original crash density here, and sliding-window risk segments in the Segment workflow."
    )

    st_folium(
        fmap,
        width=1200,
        height=900,
        key=(
            "crash_assignment_map_"
            + str(analysis_type)
            + "_"
            + str(unit_display_option)
            + "_"
            + str(intersection_display_option)
            + "_"
            + "_".join(selected_map_layers)
            + "_"
            + str(len(spatial_units_map_for_display))
            + "_"
            + str(len(assigned_crashes_for_display))
        ),
    )
