"""Step 1 road upload UI."""


def _candidate_road_class_columns(gdf):
    """Return all user-selectable attribute columns for road filtering."""
    if gdf is None or gdf.empty:
        return []

    return [
        c for c in gdf.columns
        if c != "geometry"
    ]


def _clear_downstream_results_after_road_change():
    """Clear layers/results that depend on the analysis road network."""

    for k in [
        "signals_clean",
        "signals_with_corridor",
        "signals_for_corridors",
        "corridor_signal_summary",
        "corridors",
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

        road_class_col = st.selectbox(
            "Road class/type column",
            [""] + class_cols,
            index=0,
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

        for k in [
            "signals_clean",
            "signals_with_corridor",
            "signals_for_corridors",
            "corridor_signal_summary",
            "corridors",
            "spatial_units",
            "assigned_crashes",
            "kabco_result",
            "section7_results",
            "section7_original_density",
            "section7_crashes_for_map"
        ]:
            st.session_state.pop(
                k,
                None
            )
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
        "Choose road source",
        [
            "Upload custom road network",
            "Use TIGER roads + PLACE boundary"
        ],
        index=0,
        horizontal=True
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

        if roads_file and places_file:

            roads = load_vector(
                roads_file
            ).to_crs(
                4326
            )

            places = load_vector(
                places_file
            ).to_crs(
                4326
            )

            st.success(
                "TIGER files loaded."
            )

            use_all_roads = st.checkbox(
                "Use all roads without city clipping"
            )

            if not use_all_roads:

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

            if st.button(
                "Generate FromMile and ToMile",
                key="generate_tiger_from_to_mile"
            ):

                base_roads = generate_from_to_mile(
                    roads=base_roads,
                    route_col=route_col,
                    segment_id_col=segment_id_col,
                    direction_method="Auto Detect",
                    start_mile=0.0
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

                st.success(
                    "FromMile and ToMile generated."
                )

            elif "base_roads" not in st.session_state:

                st.info(
                    "TIGER files loaded. Click Generate FromMile and ToMile."
                )

    # =====================================================
    # Option B: Custom uploaded road network
    # =====================================================
    else:

        st.subheader("Upload custom road network")

        st.info(
            "Upload shapefile components together "
            "(.shp, .dbf, .shx, .prj)."
        )

        custom_road_files = st.file_uploader(
            "Upload road shapefile ZIP or components",
            type=[
                "zip",
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

            except Exception:

                st.error(
                    "Unable to read shapefile. "
                    "Please upload .shp, .dbf, .shx, and .prj together."
                )

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

            direction_method = st.radio(
                "Route direction method for FromMile / ToMile",
                [
                    "Auto Detect",
                    "East-West",
                    "North-South"
                ],
                horizontal=True,
                index=0
            )

            if st.button(
                "Generate FromMile and ToMile"
            ):

                base_roads = generate_from_to_mile(
                    roads=roads,
                    route_col=route_col,
                    segment_id_col=segment_id_col,
                    direction_method=direction_method,
                    start_mile=0.0
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

                st.success(
                    "FromMile and ToMile generated."
                )

            else:

                if "base_roads" not in st.session_state:
                    st.info(
                        "Select fields, then click Generate FromMile and ToMile."
                    )

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

        col_reset1, col_reset2 = st.columns(2)

        with col_reset1:

            if st.button(
                "Reset analysis results"
            ):

                _clear_downstream_results_after_road_change()

                st.rerun()

        with col_reset2:

            if st.button(
                "Reset roads and start over"
            ):

                for k in [
                    "base_roads",
                    "selected_roads",
                    "selected_boundary",
                    "analysis_roads",
                    "analysis_road_class_col",
                    "analysis_road_class_values",
                    "analysis_road_filter_signature",
                    "roads_map_display",
                    "roads_class_display",
                    "road_class_viz_col",
                    "road_class_viz_values",
                    "road_class_layer_enabled",
                    "road_class_legend_enabled",
                    "route_col",
                    "segment_id_col",
                    "signals_clean",
                    "signals_with_corridor",
                    "signals_for_corridors",
                    "corridor_signal_summary",
                    "corridors",
                    "corridor_shp_bytes",
                    "crashes",
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

                st.rerun()

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

        from_to_download_cols = []

        for c in [
            st.session_state.get("route_col"),
            st.session_state.get("segment_id_col"),
            "FULLNAME",
            "RouteName_Calc",
            "FromMile",
            "ToMile",
            "SegmentLength_Mile",
            st.session_state.get("analysis_road_class_col")
        ]:
            if (
                c is not None
                and c in analysis_roads.columns
                and c not in from_to_download_cols
            ):
                from_to_download_cols.append(c)

        if not from_to_download_cols:
            from_to_download_cols = [
                c for c in analysis_roads.columns
                if c != "geometry"
            ]

        csv = analysis_roads[
            from_to_download_cols
        ].to_csv(
            index=False
        )

        st.download_button(
            "Download Analysis Roads FromMile / ToMile CSV",
            data=csv,
            file_name="analysis_roads_from_to_mile.csv",
            mime="text/csv"
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
