"""Step 4 crash upload and filtering UI."""


def render_crashes_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    selected_roads = st.session_state.get("selected_roads", None)
    selected_boundary = st.session_state.get("selected_boundary", None)
    signals_clean = st.session_state.get("signals_clean", None)
    corridors = st.session_state.get("corridors", None)

    # -----------------------------
    # 4. Upload crash data
    # -----------------------------

    area_name = st.session_state.get(
        "area_name",
        "Study Area"
    )

    route_col = st.session_state.get(
        "route_col",
        "FULLNAME"
    )

    segment_id_col = st.session_state.get(
        "segment_id_col",
        None
    )

    crash_file = st.file_uploader(
        "Upload crash CSV or Excel file",
        type=["csv", "xlsx", "xls"],
        key="crash_file"
    )

    crashes = st.session_state.get(
        "crashes",
        None
    )

    if crash_file:

        crash_df = load_crash_file(
            crash_file
        )

        try:

            crashes = crash_points(
                crash_df
            ).to_crs(4326)

            if selected_boundary is not None:

                crashes = (
                    gpd.sjoin(
                        crashes,
                        selected_boundary[["geometry"]],
                        predicate="within"
                    )
                    .drop(
                        columns=["index_right"]
                    )
                )

            st.markdown("**Crash data filters**")

            def _find_first_column(candidates):
                normalized = {
                    str(c).lower().replace(" ", "_"): c
                    for c in crashes.columns
                }

                for name in candidates:
                    if name in normalized:
                        return normalized[name]

                return None

            preferred_filters = []

            year_col = _find_first_column([
                "year",
                "crash_year",
                "u_year",
                "crash_yr",
                "yr"
            ])

            kabco_col = _find_first_column([
                "kabco",
                "k_a_b_c_o",
                "severity",
                "crash_severity",
                "injury_severity"
            ])

            crash_type_col = _find_first_column([
                "crash_type",
                "collision_type",
                "manner_of_collision",
                "first_harmful_event",
                "type"
            ])

            for label, col in [
                ("Year", year_col),
                ("KABCO", kabco_col),
                ("Crash Type", crash_type_col),
            ]:
                if col is not None and col not in [item[1] for item in preferred_filters]:
                    preferred_filters.append((label, col))

            if preferred_filters:

                for label, col in preferred_filters:

                    values = sorted(
                        crashes[col]
                        .dropna()
                        .astype(str)
                        .unique()
                    )

                    selected_values = st.multiselect(
                        label,
                        values,
                        default=values,
                        key=f"filter_{label.lower().replace(' ', '_')}_{col}"
                    )

                    crashes = crashes[
                        crashes[col]
                        .astype(str)
                        .isin(selected_values)
                    ].copy()

            else:

                st.info(
                    "No Year, KABCO, or Crash Type filter columns detected."
                )

            st.session_state[
                "crashes"
            ] = crashes

            st.success(
                f"Crash points loaded after filters: {len(crashes)}"
            )

        except Exception as e:

            st.error(
                str(e)
            )

    if crashes is not None:

        fmap = make_map(
            boundary=selected_boundary,
            roads=selected_roads,
            signals=signals_clean,
            corridors=corridors,
            crashes=crashes
        )

        st_folium(
            fmap,
            width=1200,
            height=900,
            key="crash_upload_map"
        )
