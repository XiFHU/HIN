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


def _format_spatial_unit_label(analysis_type, singular=True):
    text = str(analysis_type or "spatial unit").lower()
    if "intersection" in text:
        return "intersection" if singular else "intersections"
    if "corridor" in text:
        return "corridor" if singular else "corridors"
    if "segment" in text:
        return "segment" if singular else "segments"
    return "spatial unit" if singular else "spatial units"


def _ensure_length_miles(gdf):
    if gdf is None or gdf.empty or "Length_Miles" in gdf.columns:
        return gdf
    out = gdf.copy()
    try:
        proj = out.to_crs(epsg=3857)
        out["Length_Miles"] = proj.geometry.length / 1609.344
    except Exception:
        out["Length_Miles"] = 0.0
    return out


def _apply_priority_display_controls(spatial_units_map, analysis_type):
    """Compact map-level filter for top X / top X% priority spatial units.

    The full analysis table remains available. This controls the units drawn on
    the map so the left workflow panel stays clean.
    """
    if spatial_units_map is None or spatial_units_map.empty:
        return spatial_units_map, "All units"

    unit_label = _format_spatial_unit_label(analysis_type, singular=True)
    units_label = _format_spatial_unit_label(analysis_type, singular=False)

    rank_candidates = [
        "CrashDensity",
        "CrashCount",
        "EPDO",
        "KSI_Count",
        "Fatal_Injury_Count",
    ]
    rank_options = [c for c in rank_candidates if c in spatial_units_map.columns]
    if not rank_options:
        rank_options = ["CrashCount"] if "CrashCount" in spatial_units_map.columns else []

    container = st.popover("Priority display ▾") if hasattr(st, "popover") else st.expander("Priority display options", expanded=False)
    with container:
        st.caption(
            "Controls which priority units are displayed on this map. "
            "This does not rerun crash assignment."
        )
        mode = st.selectbox(
            "Show",
            [
                "All units",
                f"Top X {units_label}",
                f"Top X% of {units_label}",
                "Top X% of length",
                "Manual crash-density threshold",
            ],
            key=f"priority_display_mode_{analysis_type}",
        )

        rank_by = None
        if mode not in ["All units", "Manual crash-density threshold"] and rank_options:
            rank_by = st.selectbox(
                "Rank by",
                rank_options,
                index=rank_options.index("CrashDensity") if "CrashDensity" in rank_options else 0,
                key=f"priority_rank_by_{analysis_type}",
            )

        top_n = None
        top_pct = None
        threshold = None
        if mode == f"Top X {units_label}":
            top_n = st.number_input(
                f"Number of top {units_label}",
                min_value=1,
                value=min(20, max(1, len(spatial_units_map))),
                step=1,
                key=f"priority_top_n_{analysis_type}",
            )
        elif mode in [f"Top X% of {units_label}", "Top X% of length"]:
            top_pct = st.number_input(
                "Top percent",
                min_value=0.1,
                max_value=100.0,
                value=10.0,
                step=0.5,
                key=f"priority_top_pct_{analysis_type}",
            )
        elif mode == "Manual crash-density threshold":
            threshold = st.number_input(
                "Minimum crash density to display",
                min_value=0.0,
                value=0.0,
                step=1.0,
                key=f"priority_density_threshold_{analysis_type}",
            )

    out = spatial_units_map.copy()
    if mode == "All units":
        return out, f"Showing all {units_label}"

    if mode == "Manual crash-density threshold":
        if "CrashDensity" not in out.columns:
            st.warning("CrashDensity is not available for the manual threshold filter.")
            return out, f"Showing all {units_label}"
        values = pd.to_numeric(out["CrashDensity"], errors="coerce").fillna(0)
        selected = out[values >= float(threshold)].copy()
        return selected, f"Showing {len(selected):,} {units_label} with CrashDensity >= {float(threshold):g}"

    if rank_by is None or rank_by not in out.columns:
        st.warning("The selected ranking field is not available. Showing all units.")
        return out, f"Showing all {units_label}"

    out["__priority_rank_value__"] = pd.to_numeric(out[rank_by], errors="coerce").fillna(0)
    ranked = out.sort_values("__priority_rank_value__", ascending=False).copy()

    if mode == f"Top X {units_label}":
        n = max(1, int(top_n))
        selected = ranked.head(n).drop(columns=["__priority_rank_value__"], errors="ignore")
        return selected, f"Showing top {len(selected):,} {units_label} by {rank_by}"

    if mode == f"Top X% of {units_label}":
        pct = float(top_pct)
        n = max(1, int(round(len(ranked) * pct / 100.0)))
        selected = ranked.head(n).drop(columns=["__priority_rank_value__"], errors="ignore")
        return selected, f"Showing top {pct:g}% of {units_label} by {rank_by} ({len(selected):,} of {len(ranked):,})"

    if mode == "Top X% of length":
        ranked = _ensure_length_miles(ranked)
        if "Length_Miles" not in ranked.columns or pd.to_numeric(ranked["Length_Miles"], errors="coerce").fillna(0).sum() <= 0:
            pct = float(top_pct)
            n = max(1, int(round(len(ranked) * pct / 100.0)))
            selected = ranked.head(n).drop(columns=["__priority_rank_value__"], errors="ignore")
            return selected, f"Length unavailable; showing top {pct:g}% of {units_label} by {rank_by}"
        ranked["__length__"] = pd.to_numeric(ranked["Length_Miles"], errors="coerce").fillna(0)
        total_len = float(ranked["__length__"].sum())
        target_len = total_len * float(top_pct) / 100.0
        ranked["__cum_length__"] = ranked["__length__"].cumsum()
        selected = ranked[ranked["__cum_length__"] <= target_len].copy()
        if selected.empty:
            selected = ranked.head(1).copy()
        else:
            # Include the first segment that crosses the target so the selected
            # network share is at least the requested value.
            next_rows = ranked[ranked["__cum_length__"] > target_len].head(1)
            if not next_rows.empty:
                selected = pd.concat([selected, next_rows], ignore_index=False)
        selected_len = float(selected["__length__"].sum())
        selected = selected.drop(
            columns=["__priority_rank_value__", "__length__", "__cum_length__"],
            errors="ignore",
        )
        return selected, f"Showing top {float(top_pct):g}% of length by {rank_by} ({selected_len:.2f} of {total_len:.2f} mi)"

    return out.drop(columns=["__priority_rank_value__"], errors="ignore"), f"Showing all {units_label}"


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

    display_col, layer_col = st.columns([0.34, 0.66])

    with display_col:
        spatial_units_map_for_display, priority_display_summary = _apply_priority_display_controls(
            spatial_units_map,
            analysis_type,
        )

    st.caption(priority_display_summary)

    unit_display_option = "Priority display"
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

    with layer_col:
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
