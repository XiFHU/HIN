"""Step 1 road upload UI."""


def _candidate_road_class_columns(gdf):
    """Return all user-selectable attribute columns for road map styling.

    The user can choose any uploaded field as the road class/type display
    column. The selection only controls map symbology and filtering; it does
    not change the analysis road network.
    """
    if gdf is None or gdf.empty:
        return []

    return [c for c in gdf.columns if c != "geometry"]


def _apply_optional_road_class_visualization(selected_roads):
    """Optional folded road class/type styling.

    This only creates a SECOND map layer when the user explicitly enables it.
    If the option is not enabled, the map stays simple: one complete gray
    road-network layer generated from FromMile/ToMile.
    """
    if selected_roads is None or selected_roads.empty:
        st.session_state["roads_class_display"] = None
        st.session_state["road_class_layer_enabled"] = False
        return None

    roads_class_display = None

    with st.expander("Optional: road class/type map styling", expanded=False):
        st.caption(
            "Optional display setting only. Keep this off for the fastest/simple road map. "
            "Turn it on only when you want a second layer colored by a selected road attribute. "
            "This does not change the analysis road network."
        )

        enable_class_layer = st.checkbox(
            "Create Roads by Class/Type layer",
            value=bool(st.session_state.get("road_class_layer_enabled", False)),
            key="road_class_layer_enabled"
        )

        class_cols = _candidate_road_class_columns(selected_roads)

        if not enable_class_layer:
            st.info(
                "Road class/type layer is off. The map will show one complete Roads layer only."
            )
            st.session_state["roads_class_display"] = None
            st.session_state["show_roads_class_type"] = False
            return None

        st.checkbox(
            "Show Road Class/Type legend",
            value=bool(st.session_state.get("road_class_legend_enabled", True)),
            key="road_class_legend_enabled",
            help="When on, the road class/type legend appears on any workflow map when a Roads by Class/Type layer is visible. You can still turn the layer itself on/off from the map layer control."
        )

        if not class_cols:
            st.info(
                "No road attribute columns were found for optional styling. The roads are still used for analysis and shown with the default Roads layer."
            )
            st.session_state["roads_class_display"] = None
            return None

        default_col = st.session_state.get("road_class_viz_col", None)
        default_index = class_cols.index(default_col) if default_col in class_cols else 0

        road_class_col = st.selectbox(
            "Road class/type column",
            [""] + class_cols,
            index=0,
            key="road_class_viz_col"
        )

        if road_class_col == "":
            st.info(
                "Select a road class/type column to create "
                "Roads by Class/Type layers."
            )
            st.session_state["roads_class_display"] = None
            st.session_state["show_roads_class_type"] = False
            return None

        values = sorted(
            selected_roads[road_class_col]
            .dropna()
            .astype(str)
            .unique()
        )

        # Avoid selecting thousands of ID-like values by default. The user can
        # still choose any column/value, but we do not automatically create a
        # huge layer-control list or large colored layer from IDs.
        default_values = st.session_state.get("road_class_viz_values", None)
        if default_values is None:
            if len(values) <= 20:
                default_values = values
            else:
                default_values = values[:20]
        default_values = [v for v in default_values if v in values]

        selected_values = st.multiselect(
            "Road classes/types to show in this optional layer",
            values,
            default=default_values,
            key="road_class_viz_values"
        )

        if selected_values:
            roads_class_display = selected_roads[
                selected_roads[road_class_col].astype(str).isin(selected_values)
            ].copy()
        else:
            roads_class_display = selected_roads.iloc[0:0].copy()

        if not roads_class_display.empty:
            roads_class_display["RoadStyleClass"] = (
                roads_class_display[road_class_col]
                .astype(str)
                .replace({"nan": "Unknown", "None": "Unknown"})
            )

        st.caption(
            f"Optional class/type layer: {len(roads_class_display):,} of {len(selected_roads):,} roads. "
            "The complete Roads layer is still kept separately."
        )

    st.session_state["roads_class_display"] = roads_class_display

    if roads_class_display is not None and not roads_class_display.empty:
        st.session_state["show_roads_class_type"] = True
        st.session_state["active_map_layer"] = "Roads by Class/Type"
    else:
        st.session_state["show_roads_class_type"] = False

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
    selected_roads = None
    selected_boundary = None

    # =====================================================
    # Option A: Original TIGER workflow
    # =====================================================
    if road_source == "Use TIGER roads + PLACE boundary":

        st.subheader("Upload TIGER files")

        col1, col2 = st.columns(2)

        with col1:
            roads_file = st.file_uploader(
                "Upload county TIGER roads ZIP",
                type=["zip", "gpkg", "geojson", "json"],
                key="tiger_roads_file"
            )

        with col2:
            places_file = st.file_uploader(
                "Upload state PLACE ZIP",
                type=["zip", "gpkg", "geojson", "json"],
                key="places_file"
            )

        if roads_file and places_file:

            roads = load_vector(roads_file).to_crs(4326)
            places = load_vector(places_file).to_crs(4326)

            st.success("TIGER files loaded.")

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
                st.session_state["area_name"] = area_name

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
                st.session_state["area_name"] = area_name

                city_roads = roads.copy()

                selected_boundary = gpd.GeoDataFrame(
                    geometry=[
                        roads.geometry.union_all().convex_hull
                    ],
                    crs=roads.crs
                )

            road_classes = get_road_classes(city_roads)

            with st.expander("Optional: TIGER road class filter", expanded=False):
                st.caption(
                    "Optional. Filter TIGER roads by RTTYP for analysis and display. "
                    "Leave all selected to use the full selected network."
                )

                selected_classes = st.multiselect(
                    "Road classes to keep",
                    road_classes,
                    default=road_classes
                )

            selected_roads = filter_road_classes(
                city_roads,
                selected_classes
            )

            selected_roads = selected_roads.copy()

            st.session_state["active_map_layer"] = "Roads"

            route_col = "FULLNAME"
            segment_id_col = "LINEARID" if "LINEARID" in selected_roads.columns else selected_roads.columns[0]

            st.session_state["route_col"] = route_col
            st.session_state["segment_id_col"] = segment_id_col

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

            roads = roads.to_crs(4326)

            st.success(
                "Custom road network loaded."
            )

            area_name = st.text_input(
                "Enter study area name",
                value="Custom Road Network"
            )

            st.session_state["area_name"] = area_name

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

            if st.button("Generate FromMile and ToMile"):

                selected_roads = generate_from_to_mile(
                    roads=roads,
                    route_col=route_col,
                    segment_id_col=segment_id_col,
                    direction_method=direction_method,
                    start_mile=0.0
                )

                selected_roads = selected_roads.to_crs(4326)

                selected_boundary = gpd.GeoDataFrame(
                    geometry=[
                        selected_roads.geometry.union_all().convex_hull
                    ],
                    crs=selected_roads.crs
                )

                st.session_state["selected_roads"] = selected_roads
                st.session_state["selected_boundary"] = selected_boundary
                st.session_state["route_col"] = route_col
                st.session_state["segment_id_col"] = segment_id_col
                st.session_state["active_map_layer"] = "Roads"

                st.success("FromMile and ToMile generated.")

            else:
                if "selected_roads" not in st.session_state:
                    st.info("Select fields, then click Generate FromMile and ToMile.")

    if selected_roads is None and "selected_roads" in st.session_state:
        selected_roads = st.session_state["selected_roads"]

    if selected_boundary is None and "selected_boundary" in st.session_state:
        selected_boundary = st.session_state["selected_boundary"]

    if selected_roads is not None:

        selected_roads = selected_roads.copy()

        if "RoadClass" in selected_roads.columns:
            selected_roads["RoadClass"] = selected_roads["RoadClass"].fillna("Unknown")

        if "RoadType" in selected_roads.columns:
            selected_roads["RoadType"] = selected_roads["RoadType"].fillna("Unknown")

        roads_class_display = _apply_optional_road_class_visualization(selected_roads)

        st.session_state["selected_boundary"] = selected_boundary
        st.session_state["selected_roads"] = selected_roads

        col_reset1, col_reset2 = st.columns(2)

        with col_reset1:
            if st.button("Reset analysis results"):

                for k in [
                    "signals_clean",
                    "signals_with_corridor",
                    "corridor_signal_summary",
                    "corridors",
                    "crashes",
                    "spatial_units",
                    "assigned_crashes",
                    "kabco_result",
                    "analysis_type",
                    "classified",
                    "unit_col",
                    "section7_results",
                    "section7_original_density",
                    "section7_crashes_for_map"
                ]:
                    st.session_state.pop(k, None)

                st.rerun()

        with col_reset2:
            if st.button("Reset roads and start over"):

                for k in [
                    "selected_roads",
                    "selected_boundary",
                    "roads_map_display",
                    "roads_class_display",
                    "road_class_viz_col",
                    "road_class_viz_values",
                    "road_class_layer_enabled",
                    "route_col",
                    "segment_id_col",
                    "signals_clean",
                    "signals_with_corridor",
                    "corridor_signal_summary",
                    "corridors",
                    "crashes",
                    "spatial_units",
                    "assigned_crashes",
                    "kabco_result",
                    "analysis_type",
                    "classified",
                    "unit_col",
                    "section7_results",
                    "section7_original_density",
                    "section7_crashes_for_map"
                ]:
                    st.session_state.pop(k, None)

                st.rerun()

        st.write(f"Selected roads: {len(selected_roads)}")

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
            "MTFCC"
        ]

        road_table_cols = []

        for c in raw_road_table_cols:
            if c is not None and c in selected_roads.columns and c not in road_table_cols:
                road_table_cols.append(c)

        with st.expander("Selected road attributes", expanded=False):

            if road_table_cols:
                st.dataframe(
                    selected_roads[road_table_cols].drop_duplicates(),
                    width="stretch"
                )
            else:
                st.info("No displayable road attribute columns found.")

        from_to_download_cols = []
        for c in [
            st.session_state.get("route_col"),
            st.session_state.get("segment_id_col"),
            "FULLNAME",
            "RouteName_Calc",
            "FromMile",
            "ToMile",
            "SegmentLength_Mile",
        ]:
            if c is not None and c in selected_roads.columns and c not in from_to_download_cols:
                from_to_download_cols.append(c)

        if not from_to_download_cols:
            from_to_download_cols = [
                c for c in selected_roads.columns
                if c != "geometry"
            ]

        csv = selected_roads[from_to_download_cols].to_csv(index=False)

        st.download_button(
            "Download FromMile / ToMile CSV",
            data=csv,
            file_name="roads_from_to_mile.csv",
            mime="text/csv"
        )

        fmap = make_map(
            boundary=selected_boundary,
            roads=selected_roads,
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
            st.session_state["show_roads_class_type"] = False
