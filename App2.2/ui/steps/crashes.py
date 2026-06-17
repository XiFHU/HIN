"""Step 4 crash upload and filtering UI."""


def derive_kabco_from_count_columns(
    df,
    pd,
    k_col=None,
    a_col=None,
    b_col=None,
    c_col=None,
    o_col=None
):
    df = df.copy()

    severity_columns = [
        ("K", k_col),
        ("A", a_col),
        ("B", b_col),
        ("C", c_col),
        ("O", o_col),
    ]

    def classify_row(row):

        for severity, col in severity_columns:

            if col is None:
                continue

            if col not in row.index:
                continue

            value = pd.to_numeric(
                row[col],
                errors="coerce"
            )

            if pd.notna(value) and value > 0:
                return severity

        return "O"

    df["KABCO"] = df.apply(
        classify_row,
        axis=1
    )

    return df


def render_crashes_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    selected_roads = st.session_state.get("selected_roads", None)
    roads_class_display = st.session_state.get("roads_class_display", None)
    selected_boundary = st.session_state.get("selected_boundary", None)
    signals_clean = st.session_state.get("signals_clean", None)
    corridors = st.session_state.get("corridors", None)

    crash_file = st.file_uploader(
        "Upload crash CSV or Excel file",
        type=[
            "csv",
            "xlsx",
            "xls"
        ],
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
            ).to_crs(
                4326
            )

            st.markdown(
                "**Crash severity format**"
            )

            severity_format = st.radio(
                "Choose severity format",
                [
                    "Single KABCO / severity column",
                    "Five numeric KABCO count columns"
                ],
                horizontal=False,
                key="crash_severity_format"
            )

            if severity_format == "Five numeric KABCO count columns":

                crash_columns = [
                    ""
                ] + [
                    c for c in crashes.columns
                    if c != "geometry"
                ]

                k_col = st.selectbox(
                    "K / Fatal count column",
                    crash_columns,
                    index=0,
                    key="kabco_k_count_col"
                )

                a_col = st.selectbox(
                    "A / Serious injury count column",
                    crash_columns,
                    index=0,
                    key="kabco_a_count_col"
                )

                b_col = st.selectbox(
                    "B / Minor injury count column",
                    crash_columns,
                    index=0,
                    key="kabco_b_count_col"
                )

                c_col = st.selectbox(
                    "C / Possible injury count column",
                    crash_columns,
                    index=0,
                    key="kabco_c_count_col"
                )

                o_col = st.selectbox(
                    "O / No injury count column",
                    crash_columns,
                    index=0,
                    key="kabco_o_count_col"
                )

                if all(
                    [
                        k_col,
                        a_col,
                        b_col,
                        c_col,
                        o_col
                    ]
                ):

                    crashes = derive_kabco_from_count_columns(
                        crashes,
                        pd=pd,
                        k_col=k_col,
                        a_col=a_col,
                        b_col=b_col,
                        c_col=c_col,
                        o_col=o_col
                    )

                    st.caption(
                        "KABCO was derived using highest severity present per crash: "
                        "K > A > B > C > O."
                    )

                else:

                    st.info(
                        "Select all five KABCO count columns to continue."
                    )

                    return
            if selected_boundary is not None:

                crashes = (
                    gpd.sjoin(
                        crashes,
                        selected_boundary[
                            [
                                "geometry"
                            ]
                        ],
                        predicate="within"
                    )
                    .drop(
                        columns=[
                            "index_right"
                        ]
                    )
                )

            st.markdown(
                "**Crash data filters**"
            )

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

            year_col = _find_first_column(
                [
                    "year",
                    "crash_year",
                    "u_year",
                    "crash_yr",
                    "yr"
                ]
            )

            kabco_col = _find_first_column(
                [
                    "kabco",
                    "k_a_b_c_o",
                    "severity",
                    "crash_severity",
                    "injury_severity"
                ]
            )

            crash_type_col = _find_first_column(
                [
                    "crash_type",
                    "collision_type",
                    "manner_of_collision",
                    "first_harmful_event",
                    "type"
                ]
            )

            for label, col in [
                (
                    "Year",
                    year_col
                ),
                (
                    "KABCO",
                    kabco_col
                ),
                (
                    "Crash Type",
                    crash_type_col
                ),
            ]:
                if (
                    col is not None
                    and col not in [
                        item[1]
                        for item in preferred_filters
                    ]
                ):
                    preferred_filters.append(
                        (
                            label,
                            col
                        )
                    )

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

            st.session_state[
                "active_map_layer"
            ] = "Crashes"

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
            roads_class=roads_class_display,
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
