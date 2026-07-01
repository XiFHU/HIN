"""OSM signal generation UI."""

from modules.defaults import SIGNAL_DEFAULTS


def render_signals_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    selected_roads = st.session_state.get("selected_roads", None)
    roads_class_display = st.session_state.get("roads_class_display", None)
    selected_boundary = st.session_state.get("selected_boundary", None)
    city_name = st.session_state.get("area_name", "Study Area")

    signals_clean = st.session_state.get("signals_clean", None)

    if selected_boundary is not None:

        signal_distance = SIGNAL_DEFAULTS["duplicate_signal_distance_m"]
        road_snap_distance = SIGNAL_DEFAULTS["road_snap_distance_ft"]

        st.caption(
            "Signals are required before building intersections or corridors. "
            "Only the signal thresholds below are optional."
        )

        with st.expander("Signal threshold settings (optional)", expanded=False):
            customize_signal_settings = st.checkbox(
                "Customize signal thresholds",
                value=False,
                key="customize_signal_thresholds"
            )

            if customize_signal_settings:
                signal_distance = st.number_input(
                    "Duplicate signal distance (meters)",
                    min_value=10,
                    max_value=100,
                    value=SIGNAL_DEFAULTS["duplicate_signal_distance_m"],
                    step=5,
                    key="signal_duplicate_distance_m"
                )

                road_snap_distance = st.number_input(
                    "Maximum distance from road (feet)",
                    min_value=25,
                    max_value=500,
                    value=SIGNAL_DEFAULTS["road_snap_distance_ft"],
                    step=25,
                    key="signal_road_snap_distance_ft"
                )
            else:
                st.caption(
                    f"Using defaults: duplicate distance {signal_distance} m; "
                    f"road snap distance {road_snap_distance} ft."
                )

        if signals_clean is not None and not signals_clean.empty:
            st.success(
                f"Existing cleaned signals are available: {len(signals_clean):,}. "
                "Use the button below only if you want to refresh them."
            )

        signal_source = st.radio(
            "Choose signal source",
            [
                "Download OSM traffic signals",
                "Upload signal point file"
            ],
            index=0,
            key="signal_source_choice"
        )

        if signal_source == "Download OSM traffic signals":
            if st.button("Generate Signals"):

                with st.spinner(
                    "Downloading OSM traffic signals and removing duplicates..."
                ):

                    try:
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

                        signals_clean["City"] = city_name

                        st.session_state[
                            "signals_clean"
                        ] = signals_clean
                        st.session_state["signal_source_label"] = "OSM traffic signals"

                        st.session_state.pop(
                            "signals_with_corridor",
                            None
                        )

                        st.session_state.pop(
                            "signals_for_corridors",
                            None
                        )

                        st.session_state.pop(
                            "corridors",
                            None
                        )

                        st.session_state.pop(
                            "final_corridors",
                            None
                        )

                        st.session_state.pop(
                            "dropped_corridor_ids",
                            None
                        )

                        st.session_state.pop(
                            "applied_dropped_corridor_ids",
                            None
                        )

                        st.session_state.pop(
                            "corridor_signal_summary",
                            None
                        )

                        st.session_state.pop(
                            "spatial_units",
                            None
                        )

                        st.session_state.pop(
                            "assigned_crashes",
                            None
                        )

                        st.session_state.pop(
                            "kabco_result",
                            None
                        )

                        st.session_state.pop(
                            "section7_results",
                            None
                        )

                        st.session_state[
                            "active_map_layer"
                        ] = "Signals"

                        if signals_clean.empty:
                            st.warning(
                                "No OSM traffic signal points were found inside "
                                "the selected study area after duplicate removal "
                                "and road-distance filtering."
                            )
                        else:
                            st.success(
                                f"Generated {len(signals_clean):,} cleaned OSM traffic signals."
                            )

                    except Exception as e:
                        st.error(
                            "Unable to download OSM traffic signals from public "
                            "Overpass servers. This is usually a temporary "
                            "server/rate-limit issue, not a FARS crash-data issue."
                        )
                        st.info(
                            "You can retry later, switch to 'Upload signal point file', "
                            "or continue the segment/sliding-window workflow if signals "
                            "are not required for your current analysis."
                        )
                        st.caption(
                            str(e)
                        )
        else:
            st.caption(
                "Upload signal points as CSV/XLSX/GeoJSON/GPKG/Shapefile ZIP. "
                "The table must include a signal ID field and latitude/longitude fields unless geometry already exists."
            )
            signal_file = st.file_uploader(
                "Upload signal point file",
                type=["csv", "xlsx", "xls", "geojson", "json", "gpkg", "zip"],
                key="uploaded_signal_file"
            )
            if signal_file is not None:
                try:
                    uploaded = load_vector(signal_file).to_crs(4326)
                except Exception:
                    try:
                        uploaded = pd.read_csv(signal_file)
                    except Exception:
                        try:
                            uploaded = pd.read_excel(signal_file)
                        except Exception as e:
                            st.error(f"Unable to read uploaded signal file: {e}")
                            uploaded = None

                if uploaded is not None:
                    cols = list(uploaded.columns)
                    id_guess = "SignalID" if "SignalID" in cols else cols[0]
                    id_col = st.selectbox(
                        "Signal ID column",
                        cols,
                        index=cols.index(id_guess) if id_guess in cols else 0,
                        key="uploaded_signal_id_col"
                    )
                    lat_candidates = [c for c in cols if str(c).lower() in ["lat", "latitude", "y"]]
                    lon_candidates = [c for c in cols if str(c).lower() in ["lon", "long", "longitude", "x"]]
                    has_geometry = hasattr(uploaded, "geometry") and "geometry" in cols
                    lat_col = None
                    lon_col = None
                    if not has_geometry:
                        lat_col = st.selectbox(
                            "Latitude column",
                            cols,
                            index=cols.index(lat_candidates[0]) if lat_candidates else 0,
                            key="uploaded_signal_lat_col"
                        )
                        lon_col = st.selectbox(
                            "Longitude column",
                            cols,
                            index=cols.index(lon_candidates[0]) if lon_candidates else min(1, len(cols) - 1),
                            key="uploaded_signal_lon_col"
                        )
                    if st.button("Use uploaded signals", key="use_uploaded_signals"):
                        try:
                            if has_geometry:
                                signals_clean = uploaded.copy().to_crs(4326)
                            else:
                                temp = uploaded.copy()
                                temp[lat_col] = pd.to_numeric(temp[lat_col], errors="coerce")
                                temp[lon_col] = pd.to_numeric(temp[lon_col], errors="coerce")
                                temp = temp.dropna(subset=[lat_col, lon_col])
                                signals_clean = gpd.GeoDataFrame(
                                    temp,
                                    geometry=gpd.points_from_xy(temp[lon_col], temp[lat_col]),
                                    crs="EPSG:4326"
                                )
                            signals_clean = signals_clean[signals_clean.geometry.notna()].copy()
                            signals_clean = signals_clean[~signals_clean.geometry.is_empty].copy()
                            if selected_roads is not None and not signals_clean.empty:
                                signals_clean = filter_signals_to_roads(
                                    signals_clean,
                                    selected_roads,
                                    max_distance_ft=road_snap_distance
                                )
                            signals_clean = signals_clean.reset_index(drop=True)
                            signals_clean["SignalID"] = signals_clean[id_col].astype(str) if id_col in signals_clean.columns else (signals_clean.index + 1)
                            signals_clean["City"] = city_name
                            st.session_state["signals_clean"] = signals_clean
                            st.session_state["signal_source_label"] = "Uploaded signal point file"
                            for k in [
                                "signals_with_corridor", "signals_for_corridors", "corridors", "final_corridors",
                                "dropped_corridor_ids", "applied_dropped_corridor_ids", "corridor_signal_summary",
                                "spatial_units", "assigned_crashes", "kabco_result", "section7_results"
                            ]:
                                st.session_state.pop(k, None)
                            st.session_state["active_map_layer"] = "Signals"
                            st.success(f"Loaded {len(signals_clean):,} uploaded signal points.")
                        except Exception as e:
                            st.error(f"Unable to create uploaded signal layer: {e}")

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

        display_cols = [
            c for c in [
                "SignalID",
                "City",
                "Latitude",
                "Longitude"
            ]
            if c in signals_table.columns
        ]

        signals_table = signals_table[
            display_cols
        ]

        st.dataframe(
            signals_table,
            width="stretch"
        )


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
