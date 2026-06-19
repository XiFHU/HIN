"""Step 6 map and download controls for classified crash results."""

from ..map_symbology import categorical_color_lookup, render_crash_color_controls


def _download_menu(label, items):
    """Render compact download menu. Uses st.popover when available, falls back to expander."""
    if hasattr(st, "popover"):
        menu = st.popover(label, use_container_width=False)
    else:
        menu = st.expander(label, expanded=False)

    with menu:
        for item in items:
            if item.get("kind") == "prepare_geojson":
                if st.button(item["button_label"], key=item["prepare_key"]):
                    try:
                        geojson_gdf = make_json_safe_gdf(item["gdf"].to_crs(4326))
                        geojson_bytes = geojson_gdf.to_json().encode("utf-8")
                        st.session_state[item["state_key"]] = geojson_bytes
                        st.success("Original crash density GeoJSON ready.")
                    except Exception as e:
                        st.error(f"Could not create spatial units GeoJSON: {e}")

                if item["state_key"] in st.session_state:
                    st.download_button(
                        item["download_label"],
                        st.session_state[item["state_key"]],
                        file_name=item["file_name"],
                        mime=item["mime"],
                        key=item["download_key"],
                    )
            else:
                st.download_button(
                    item["label"],
                    data=item["data"],
                    file_name=item["file_name"],
                    mime=item["mime"],
                    key=item["key"],
                )


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

    geojson_key = f"units_with_density_geojson_{analysis_type}"

    header_col, menu_col = st.columns([0.82, 0.18])
    with header_col:
        st.markdown(f"**{analysis_type} results**")
    with menu_col:
        download_items = [
            {
                "label": "Spatial Units CSV",
                "data": units_table.to_csv(index=False),
                "file_name": "spatial_units.csv",
                "mime": "text/csv",
                "key": f"download_units_csv_{analysis_type}",
            },
            {
                "label": "Assigned Crashes CSV",
                "data": assigned_table.to_csv(index=False),
                "file_name": "assigned_crashes.csv",
                "mime": "text/csv",
                "key": f"download_assigned_csv_{analysis_type}",
            },
            {
                "kind": "prepare_geojson",
                "button_label": "Prepare Current Spatial Unit Density GeoJSON",
                "download_label": "Current Spatial Unit Density GeoJSON",
                "gdf": spatial_units_map,
                "state_key": geojson_key,
                "prepare_key": f"prepare_{geojson_key}",
                "download_key": f"download_{geojson_key}",
                "file_name": "current_spatial_units_with_crash_density.geojson",
                "mime": "application/geo+json",
            },
        ]

        if kabco_result is not None:
            download_items.insert(
                2,
                {
                    "label": "KABCO / Crash Summary CSV",
                    "data": kabco_result.to_csv(index=False),
                    "file_name": "crash_summary.csv",
                    "mime": "text/csv",
                    "key": f"download_summary_{analysis_type}",
                },
            )

        _download_menu("☰", download_items)

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

    map_layer_options = [
        "Boundary",
        "Roads",
        "Signals",
        "Crash Density Spatial Units",
        "Assigned Crashes",
    ]

    active_map_layer = st.session_state.get("active_map_layer", None)

    if active_map_layer == "Crash Density Spatial Units":
        default_layers = ["Crash Density Spatial Units"]
    elif active_map_layer == "Crashes":
        default_layers = ["Assigned Crashes"]
    elif active_map_layer == "Signals":
        default_layers = ["Signals"]
    else:
        default_layers = ["Crash Density Spatial Units"]

    selected_map_layers = st.multiselect(
        "Map layers",
        map_layer_options,
        default=[layer for layer in default_layers if layer in map_layer_options],
        key=f"selected_map_layers_{analysis_type}",
        label_visibility="collapsed",
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

    crash_color_settings = {"enabled": False, "field": None}
    if crashes_layer is not None and not crashes_layer.empty:
        crash_color_settings = render_crash_color_controls(
            crashes_layer,
            key_prefix=f"results_crashes_{analysis_type}",
        )
        if crash_color_settings.get("enabled"):
            field = crash_color_settings.get("field")
            crash_color_settings["color_lookup"] = categorical_color_lookup(
                crashes_layer[field].fillna("Unknown")
            )

    fmap = make_map(
        boundary=boundary_layer,
        roads=roads_layer,
        roads_class=st.session_state.get("roads_class_display", None) if roads_layer is not None else None,
        signals=signals_layer,
        corridors=None,
        spatial_units=spatial_units_layer,
        crashes=crashes_layer,
        density_cmap=density_cmap,
        crash_color_settings=crash_color_settings,
    )

    if spatial_units_layer is not None:
        density_cmap.add_to(fmap)

    fmap = add_map_elements(fmap)

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
