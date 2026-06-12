"""Step 1 road upload UI."""


def _candidate_road_class_columns(gdf):
    """Return practical road class/type columns for optional map styling.

    This intentionally excludes segment/facility ID fields. A useful styling
    field should be categorical, not a unique ID for every road segment.
    """
    if gdf is None or gdf.empty:
        return []

    preferred_exact = [
        "RoadClass",
        "RoadType",
        "RTTYP",
        "MTFCC",
        "F_SYSTEM",
        "FUNC_CLASS",
        "FUNCTIONAL_CLASS",
        "FCLASS",
        "CLASS",
        "TYPE",
        "ROAD_CLASS",
        "ROAD_TYPE",
        "FACILITY_TYPE",
        "FEDFUNC",
        "FUNCLASS",
    ]

    id_like = [
        "id",
        "fid",
        "objectid",
        "facilityid",
        "linearid",
        "segmentid",
        "segid",
        "routeid",
        "joinid",
        "geoid",
    ]

    thematic_keywords = [
        "class",
        "type",
        "rttyp",
        "mtfcc",
        "functional",
        "func",
        "fclass",
        "roadway",
        "facility_type",
        "surface",
        "access",
        "jurisdiction",
    ]

    candidates = []

    for preferred in preferred_exact:
        if preferred in gdf.columns and preferred not in candidates:
            candidates.append(preferred)

    row_count = max(len(gdf), 1)
    max_unique = min(40, max(8, int(row_count * 0.15)))

    for col in gdf.columns:
        if col == "geometry" or col in candidates:
            continue

        name = str(col).lower().replace(" ", "_")

        # Exclude ID-style fields such as FACILITYID. Those create thousands
        # of unique map categories and are not road class/type fields.
        if name in id_like or name.endswith("_id") or name.endswith("id"):
            continue

        if not any(k in name for k in thematic_keywords):
            continue

        values = gdf[col].dropna().astype(str)
        unique_count = values.nunique()

        if unique_count < 2 or unique_count > max_unique:
            continue

        candidates.append(col)

    return candidates


def _apply_optional_road_class_visualization(selected_roads):
    """Optional folded road class/type styling.

    This only affects the map display layer. The full uploaded road network is
    still preserved in selected_roads for analysis.
    """
    if selected_roads is None or selected_roads.empty:
        return selected_roads

    roads_for_map = selected_roads.copy()

    with st.expander("Optional: road class/type map styling", expanded=False):
        st.caption(
            "Optional display setting only. Choose a categorical road class/type column, then select the values to show on the map. "
            "ID fields such as FACILITYID are intentionally excluded because they are not road classes. The full uploaded road network is still kept for analysis."
        )

        class_cols = _candidate_road_class_columns(selected_roads)

        if not class_cols:
            st.info(
                "No usable road class/type column was detected. This is optional; the roads are still used for analysis and shown with the default style."
            )
            st.session_state["roads_map_display"] = roads_for_map
            return roads_for_map

        default_col = st.session_state.get("road_class_viz_col", None)
        default_index = class_cols.index(default_col) if default_col in class_cols else 0

        road_class_col = st.selectbox(
            "Road class/type column",
            class_cols,
            index=default_index,
            key="road_class_viz_col"
        )

        values = sorted(
            selected_roads[road_class_col]
            .dropna()
            .astype(str)
            .unique()
        )

        default_values = st.session_state.get("road_class_viz_values", values)
        default_values = [v for v in default_values if v in values]

        selected_values = st.multiselect(
            "Road classes/types to show on map",
            values,
            default=default_values if default_values else values,
            key="road_class_viz_values"
        )

        if selected_values:
            roads_for_map = selected_roads[
                selected_roads[road_class_col].astype(str).isin(selected_values)
            ].copy()
        else:
            roads_for_map = selected_roads.iloc[0:0].copy()

        if not roads_for_map.empty:
            roads_for_map["RoadClass"] = (
                roads_for_map[road_class_col]
                .astype(str)
                .replace({"nan": "Unknown", "None": "Unknown"})
            )

        st.caption(f"Roads shown on map: {len(roads_for_map):,} of {len(selected_roads):,}")

    st.session_state["roads_map_display"] = roads_for_map
    return roads_for_map


def render_roads_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    road_source = st.radio(
        "Choose road source",
        [
            "Use TIGER roads + PLACE boundary",
            "Upload custom road network"
        ],
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

        roads_for_map = _apply_optional_road_class_visualization(selected_roads)

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
                    "road_class_viz_col",
                    "road_class_viz_values",
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

        csv = selected_roads.drop(columns="geometry").to_csv(index=False)

        st.download_button(
            "Download selected roads attribute table",
            data=csv,
            file_name="selected_roads_attributes.csv",
            mime="text/csv"
        )

        fmap = make_map(
            boundary=selected_boundary,
            roads=roads_for_map
        )

        st_folium(
            fmap,
            width=1200,
            height=900,
            key="road_map"
        )
