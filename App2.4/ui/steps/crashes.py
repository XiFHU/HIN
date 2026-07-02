"""Step 4 crash upload and filtering UI."""

from modules.fars import (
    FARS_STATE_CODES,
    build_fars_accident_data_url,
    detect_county_fips_from_boundary,
    parse_fars_accident_csv,
)
from modules.crash_field_mapping import (
    render_field_mapping_ui,
    apply_field_mapping,
    normalize_kabco_value,
)
from ..map_symbology import (
    categorical_color_lookup,
    render_crash_color_controls,
)


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
    df["DashboardKABCO"] = df["KABCO"]
    df["DashboardSeverityLabel"] = df["KABCO"]
    df["CrashSeverityLabel"] = df["DashboardSeverityLabel"]

    return df


def _clean_filter_text_series(series):
    values = (
        series
        .dropna()
        .astype(str)
        .str.strip()
    )
    values = values[
        (values != "")
        & (values.str.lower() != "nan")
        & (values.str.lower() != "none")
        & (values.str.lower() != "null")
    ]
    return values


def _unique_clean_values(df, col):
    if df is None or col is None or col not in df.columns:
        return []
    values = _clean_filter_text_series(df[col])
    if values.empty:
        return []
    return sorted(values.replace("", "Unknown").unique())


def _is_normalized_kabco_value_list(values):
    valid = {"K", "A", "B", "C", "O"}
    clean_values = {
        str(v).strip().upper()
        for v in values
        if str(v).strip() != ""
    }
    return bool(clean_values) and clean_values.issubset(valid)


def _best_original_single_severity_column(df, mapping=None):
    """
    Pick the original user-facing severity column for the single-column mode.

    This intentionally prefers agency labels such as Fatal (K), Serious Injury,
    No Injury, etc. over normalized calculation columns such as KABCO.
    If the source dataset truly only has a K/A/B/C/O text column, it can still
    return that column.
    """
    if df is None or df.empty:
        return None

    mapping = mapping or {}

    likely_names = [
        mapping.get("severity", ""),
        "Severity",
        "Crash Severity",
        "CRASH_SEVERITY",
        "CrashSeverity",
        "InjurySeverity",
        "INJURY_SEVERITY",
        "Most_Severe_Injury",
        "MOST_SEVERE_INJURY",
        "SeverityName",
        "SEVERITY",
        "k_a_b_c_o",
        "KABCO",
    ]

    existing = []
    lower_lookup = {str(c).strip().lower(): c for c in df.columns}
    compact_lookup = {
        str(c).strip().lower().replace(" ", "").replace("_", "").replace("-", ""): c
        for c in df.columns
    }

    for name in likely_names:
        if not name:
            continue
        if name in df.columns:
            col = name
        else:
            key = str(name).strip().lower()
            compact_key = key.replace(" ", "").replace("_", "").replace("-", "")
            col = lower_lookup.get(key) or compact_lookup.get(compact_key)
        if col and col not in existing:
            existing.append(col)

    scored = []
    calculation_cols = {
        "kabco",
        "dashboardkabco",
        "dashboardseveritylabel",
        "crashseveritylabel",
    }

    for col in existing:
        values = _unique_clean_values(df, col)
        if not values:
            continue

        col_key = str(col).strip().lower().replace("_", "")
        is_calc_col = col_key in calculation_cols
        is_kabco_code_only = _is_normalized_kabco_value_list(values)
        unique_count = len(values)

        # Highest priority: mapped/raw agency text labels with multiple values.
        # Lower priority: calculated columns and K/A/B/C/O-only values.
        score = 0
        if str(col) == str(mapping.get("severity", "")):
            score += 100
        if not is_calc_col:
            score += 50
        if not is_kabco_code_only:
            score += 30
        if unique_count > 1:
            score += 20
        score += min(unique_count, 10)

        scored.append((score, col, values))

    if not scored:
        return None

    scored.sort(reverse=True, key=lambda item: item[0])
    return scored[0][1]


def restore_single_severity_from_source(df, mapping=None):
    """
    Force single-column severity mode to use the mapped/original severity column.

    This prevents columns such as Fatalities/fatals/count fields from turning a
    local all-crash file into all K. FARS is handled separately by true FARS
    detection inside apply_field_mapping().
    """
    if df is None or df.empty:
        return df

    out = df.copy()
    sev_col = _best_original_single_severity_column(out, mapping)

    if sev_col is None or sev_col not in out.columns:
        return out

    labels = (
        out[sev_col]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
        .replace({"": "Unknown"})
    )

    out["DashboardSeverityLabel"] = labels
    out["CrashSeverityLabel"] = labels
    out["DashboardKABCO"] = out[sev_col].map(normalize_kabco_value)
    out["KABCO"] = out["DashboardKABCO"]
    out["SeverityFilterSourceColumn"] = sev_col

    return out


def _clear_downstream_results_after_crash_change():
    """Clear results that depend on the crash layer."""

    for k in [
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
        "section7_route_col_s7",
    ]:
        st.session_state.pop(k, None)


def _clip_crashes_to_boundary(crashes, selected_boundary):
    if selected_boundary is None or crashes is None or crashes.empty:
        return crashes

    try:
        boundary = selected_boundary[["geometry"]].copy()

        if boundary.crs != crashes.crs:
            boundary = boundary.to_crs(crashes.crs)

        clipped = (
            gpd.sjoin(
                crashes,
                boundary,
                predicate="within"
            )
            .drop(
                columns=[
                    "index_right"
                ],
                errors="ignore"
            )
        )

        return clipped.copy()

    except Exception as e:
        st.warning(
            f"Could not spatially filter crashes to the selected boundary: {e}"
        )
        return crashes


def _render_crash_filters(crashes, source_key="crash"):
    if crashes is None:
        return crashes

    crashes = crashes.copy()

    st.markdown(
        "**Crash data filters**"
    )

    def _clean_key(value):
        return (
            str(value)
            .strip()
            .lower()
            .replace(" ", "_")
            .replace("-", "_")
        )

    def _find_first_column(candidates):
        normalized = {
            _clean_key(c): c
            for c in crashes.columns
        }

        compact = {
            _clean_key(c).replace("_", ""): c
            for c in crashes.columns
        }

        for name in candidates:
            key = _clean_key(name)
            if key in normalized:
                return normalized[key]
            key_compact = key.replace("_", "")
            if key_compact in compact:
                return compact[key_compact]

        return None

    def _valid_filter_values(col):
        if col is None or col not in crashes.columns:
            return []

        values = (
            crashes[col]
            .dropna()
            .astype(str)
            .str.strip()
        )
        values = values[
            (values != "")
            & (values.str.lower() != "nan")
            & (values.str.lower() != "none")
            & (values.str.lower() != "null")
        ]

        if values.empty:
            return []

        return sorted(values.replace("", "Unknown").unique())

    def _choose_severity_filter_column():
        """Choose the user-facing severity field, not the calculation field.

        Different datasets may store severity as:
        - K/A/B/C/O only
        - text labels, e.g. Fatal, Serious Injury, No Injury
        - combined labels, e.g. Fatal (K), Evident, Incapacitating (A)

        The app creates DashboardSeverityLabel / CrashSeverityLabel during field
        mapping.  Those are the preferred filter/legend fields.  KABCO is only a
        normalized internal calculation field and is used as a last fallback.
        """

        # If the upload branch saved the true source column, use it first.
        source_col = crashes.attrs.get("SeverityFilterSourceColumn", None)
        if source_col and source_col in crashes.columns:
            values = _valid_filter_values(source_col)
            if values:
                return source_col

        if "SeverityFilterSourceColumn" in crashes.columns:
            source_values = _valid_filter_values("SeverityFilterSourceColumn")
            if source_values:
                source_col = str(crashes["SeverityFilterSourceColumn"].dropna().astype(str).iloc[0])
                if source_col in crashes.columns and _valid_filter_values(source_col):
                    return source_col

        # Prefer the mapping's original severity column before any generated
        # Dashboard/KABCO column. This is critical when a local file has both
        # a Fatalities count column and a separate Severity text column.
        mapping_candidates = []
        for state_key in [
            "upload_crash_field_mapping_values",
            "crash_field_mapping",
            "fars_crash_field_mapping_values",
        ]:
            mapping = st.session_state.get(state_key, {}) or {}
            mapped_severity = mapping.get("severity", "")
            if mapped_severity and mapped_severity not in mapping_candidates:
                mapping_candidates.append(mapped_severity)

        for mapped_severity in mapping_candidates:
            if mapped_severity and mapped_severity in crashes.columns:
                values = _valid_filter_values(mapped_severity)
                if values:
                    return mapped_severity

        likely_original_cols = [
            "Severity",
            "CRASH_SEVERITY",
            "CrashSeverity",
            "Crash Severity",
            "InjurySeverity",
            "INJURY_SEVERITY",
            "Most_Severe_Injury",
            "MOST_SEVERE_INJURY",
            "SeverityName",
            "SEVERITY",
        ]

        for col in likely_original_cols:
            found = _find_first_column([col])
            values = _valid_filter_values(found)
            if found is not None and values:
                return found

        preferred = [
            "DashboardSeverityLabel",
            "CrashSeverityLabel",
            "SeverityLabel",
            "OriginalSeverity",
            "Severity_Original",
        ]

        for col in preferred:
            found = _find_first_column([col])
            values = _valid_filter_values(found)
            if found is not None and values:
                return found

        likely_original_cols = [
            "Severity",
            "CRASH_SEVERITY",
            "CrashSeverity",
            "Crash Severity",
            "InjurySeverity",
            "INJURY_SEVERITY",
            "Most_Severe_Injury",
            "MOST_SEVERE_INJURY",
            "SeverityName",
            "SEVERITY",
        ]

        for col in likely_original_cols:
            found = _find_first_column([col])
            values = _valid_filter_values(found)
            if found is not None and values:
                return found

        # Last fallback only.  This is correct for datasets where the original
        # severity field really is K/A/B/C/O, or for FARS where all rows are K.
        return _find_first_column(["KABCO", "DashboardKABCO", "k_a_b_c_o"])

    preferred_filters = []

    year_col = _find_first_column(
        [
            "DashboardCrashYear",
            "year",
            "crash_year",
            "u_year",
            "crash_yr",
            "yr",
            "caseyear",
            "case_year"
        ]
    )

    severity_col = _choose_severity_filter_column()

    crash_type_col = _find_first_column(
        [
            "DashboardCrashType",
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
            "Crash severity",
            severity_col
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

            values = _valid_filter_values(col)

            if not values:
                continue

            value_signature = str(abs(hash(tuple(values))))
            selected_values = st.multiselect(
                label,
                values,
                default=values,
                key=f"filter_{source_key}_{label.lower().replace(' ', '_')}_{col}_{value_signature}"
            )

            if label == "Crash severity":
                st.caption(f"Severity filter source: `{col}`")

            filter_values = [str(v).strip() for v in selected_values]
            crashes = crashes[
                crashes[col]
                .fillna("Unknown")
                .astype(str)
                .str.strip()
                .replace("", "Unknown")
                .isin(filter_values)
            ].copy()

    else:

        st.info(
            "No Year, Severity, or Crash Type filter columns detected."
        )

    return crashes

def _render_data_size_and_quality_notes():
    with st.expander("App limits and data quality notes", expanded=False):
        st.markdown(
            """
- **OSM signal accuracy:** OSM signal points are volunteered/contributed data. Signal locations, missing signals, and duplicate signal nodes can affect intersection/corridor building.
- **OSM road classes:** OSM `highway` classes are useful for screening but may not match agency functional classification.
- **TIGER roads:** TIGER is broad national road geometry. It is useful for coverage, but road class/detail and geometry can be less precise than local agency centerlines.
- **Uploaded crash/FARS fields:** Different agencies use different column names. Use the Crash Field Mapping panel to confirm crash ID, date/year, crash type, severity, and injury-count fields.
- **Large datasets:** For Streamlit Cloud, keep uploads and map layers moderate. Very large OSM extracts, statewide roads, or hundreds of thousands of crashes may need pre-filtering, road-class filtering, or local workstation processing.
- **Map performance:** Interactive Folium maps can slow down when many thousands of features are drawn. Use Top N / Top percent filters for display when needed.
            """
        )


def render_crashes_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    _render_data_size_and_quality_notes()

    selected_roads = st.session_state.get("selected_roads", None)
    roads_class_display = st.session_state.get("roads_class_display", None)
    selected_boundary = st.session_state.get("selected_boundary", None)
    signals_clean = st.session_state.get("signals_clean", None)
    corridors = st.session_state.get("corridors", None)

    crash_source = st.radio(
        "Crash data source",
        [
            "Upload crash file",
            "Use FARS data — no upload"
        ],
        index=0,
        horizontal=False,
        key="crash_data_source"
    )

    previous_source = st.session_state.get(
        "_active_crash_data_source",
        None
    )

    if previous_source != crash_source:
        st.session_state["_active_crash_data_source"] = crash_source
        for k in [
            "crashes",
            "all_crashes",
            "filtered_crashes",
            "crash_data_signature",
            "crash_file",
        ]:
            st.session_state.pop(k, None)
        _clear_downstream_results_after_crash_change()

    if crash_source == "Upload crash file":

        crash_file = st.file_uploader(
            "Upload crash CSV or Excel file",
            type=[
                "csv",
                "xlsx",
                "xls"
            ],
            key="crash_file"
        )

        if crash_file:

            crash_df = load_crash_file(
                crash_file
            )

            try:

                crashes_loaded = crash_points(
                    crash_df
                ).to_crs(
                    4326
                )

                crashes_loaded.attrs["CrashSource"] = "LOCAL_UPLOAD"

                mapping = render_field_mapping_ui(
                    st,
                    crashes_loaded,
                    key_prefix="upload_crash_field_mapping"
                )
                crashes_loaded = apply_field_mapping(
                    crashes_loaded,
                    mapping
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

                if severity_format == "Single KABCO / severity column":

                    crashes_loaded = restore_single_severity_from_source(
                        crashes_loaded,
                        mapping
                    )

                    source_col = crashes_loaded.get(
                        "SeverityFilterSourceColumn",
                        None
                    )

                    if source_col is not None:
                        source_col_values = source_col.dropna().astype(str).unique()
                        if len(source_col_values) > 0:
                            st.caption(
                                f"Severity labels are read from: `{source_col_values[0]}`"
                            )

                if severity_format == "Five numeric KABCO count columns":

                    crash_columns = [
                        ""
                    ] + [
                        c for c in crashes_loaded.columns
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

                        crashes_loaded = derive_kabco_from_count_columns(
                            crashes_loaded,
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

                crashes_loaded = _clip_crashes_to_boundary(
                    crashes_loaded,
                    selected_boundary
                )

                upload_signature = (
                    "upload",
                    getattr(crash_file, "name", ""),
                    getattr(crash_file, "size", None),
                    severity_format,
                    str(locals().get("k_col", "")),
                    str(locals().get("a_col", "")),
                    str(locals().get("b_col", "")),
                    str(locals().get("c_col", "")),
                    str(locals().get("o_col", "")),
                )

                if st.session_state.get("crash_data_signature") != upload_signature:
                    _clear_downstream_results_after_crash_change()

                st.session_state["crash_data_signature"] = upload_signature
                st.session_state["all_crashes"] = crashes_loaded
                st.session_state["crash_source_label"] = "Uploaded crash file"

                st.success(
                    f"Crash points loaded before filters: {len(crashes_loaded)}"
                )

            except Exception as e:

                st.error(
                    str(e)
                )

    else:

        st.warning(
            "FARS contains fatal crashes only. Use this option when a fatal-crash-only analysis is appropriate."
        )

        st.caption(
            "No API key is required. Because NHTSA may block direct Streamlit/Python downloads, this workflow generates a browser download link. Download the CSV in your browser, then upload that CSV below."
        )

        if selected_boundary is None:
            st.info(
                "A selected road/study-area boundary is recommended. The app can still use the selected FARS state/county, but it cannot clip to your exact analysis area until a boundary exists."
            )

        state_names = list(FARS_STATE_CODES.keys())

        pending_state_name = st.session_state.pop(
            "fars_state_name_pending",
            None
        )
        if pending_state_name in state_names:
            st.session_state["fars_state_name"] = pending_state_name

        default_state_index = (
            state_names.index("Colorado")
            if "Colorado" in state_names
            else 0
        )
        state_name = st.selectbox(
            "FARS state",
            state_names,
            index=default_state_index,
            key="fars_state_name"
        )

        st.caption(
            "County can be entered manually or auto-detected from the selected study-area boundary. The FARSData download is statewide; the app filters the uploaded CSV to this county afterward."
        )

        if st.button(
            "Auto detect county code from study area",
            key="auto_detect_fars_county_code"
        ):
            try:
                detected_county = detect_county_fips_from_boundary(
                    selected_boundary
                )

                detected_state = int(
                    detected_county.get("state_fips")
                )
                detected_state_name = next(
                    (
                        name
                        for name, code in FARS_STATE_CODES.items()
                        if int(code) == detected_state
                    ),
                    None
                )

                if detected_state_name is not None:
                    st.session_state["fars_state_name_pending"] = detected_state_name

                st.session_state["fars_county_code"] = detected_county[
                    "county_fips_text"
                ]
                st.session_state["fars_county_detected_label"] = (
                    f"{detected_county.get('county_name', 'County')} "
                    f"- county code {detected_county['county_fips_text']} "
                    f"(state {detected_state_name or detected_state}; "
                    f"full GEOID {detected_county['full_county_geoid']})"
                )
                st.success(
                    "County/state detected: "
                    + st.session_state["fars_county_detected_label"]
                )
                st.rerun()

            except Exception as e:
                st.error(
                    f"Unable to auto-detect county code: {e}"
                )

        if st.session_state.get("fars_county_detected_label"):
            st.info(
                "Detected FARS county: "
                + st.session_state["fars_county_detected_label"]
            )

        if "fars_county_code" not in st.session_state:
            st.session_state["fars_county_code"] = ""

        county_code = st.text_input(
            "County FIPS code for filtering downloaded FARS data",
            help=(
                "Use the county FIPS code within the selected state. Do not enter "
                "the state prefix. For example, Arapahoe County, Colorado is 5, "
                "not 08005."
            ),
            key="fars_county_code"
        )

        st.markdown("**FARS Accident dataset download**")
        st.caption(
            "This uses the NHTSA FARSData Accident endpoint. It downloads all Accident records for the selected state and year range; county filtering happens after upload. The API documentation lists the FARSData export as available for FARS data by year."
        )

        col1, col2 = st.columns(2)

        with col1:
            from_year = st.number_input(
                "From FARS year",
                min_value=2010,
                max_value=2030,
                value=2020,
                step=1,
                key="fars_from_year"
            )

        with col2:
            to_year = st.number_input(
                "To FARS year",
                min_value=2010,
                max_value=2030,
                value=2024,
                step=1,
                key="fars_to_year"
            )

        fars_accident_url = None
        if int(to_year) < int(from_year):
            st.warning(
                "To year must be greater than or equal to From year."
            )
        else:
            fars_accident_url = build_fars_accident_data_url(
                state_code=FARS_STATE_CODES[state_name],
                from_year=int(from_year),
                to_year=int(to_year),
                output_format="csv",
            )
            st.caption(
                "Open this link in your browser, download the CSV, then upload the downloaded CSV below."
            )
            st.markdown(
                f"[Open FARS Accident CSV download link]({fars_accident_url})"
            )
            st.code(fars_accident_url, language="text")

        fars_csv_upload = st.file_uploader(
            "Upload the downloaded FARS Accident CSV",
            type=["csv"],
            key="fars_accident_browser_csv_upload"
        )

        if fars_csv_upload is not None:
            try:
                crashes_loaded = parse_fars_accident_csv(
                    fars_csv_upload,
                    county_code=county_code if str(county_code).strip() else None,
                ).to_crs(4326)

                crashes_loaded.attrs["CrashSource"] = "FARS"

                mapping = render_field_mapping_ui(
                    st,
                    crashes_loaded,
                    key_prefix="fars_crash_field_mapping"
                )
                crashes_loaded = apply_field_mapping(
                    crashes_loaded,
                    mapping
                )

                crashes_loaded = _clip_crashes_to_boundary(
                    crashes_loaded,
                    selected_boundary
                )

                fars_signature = (
                    "fars_accident_csv_upload",
                    state_name,
                    int(from_year),
                    int(to_year),
                    str(county_code).strip(),
                    getattr(fars_csv_upload, "name", ""),
                    getattr(fars_csv_upload, "size", None),
                )

                if st.session_state.get("crash_data_signature") != fars_signature:
                    _clear_downstream_results_after_crash_change()

                st.session_state["crash_data_signature"] = fars_signature
                st.session_state["all_crashes"] = crashes_loaded
                st.session_state["crash_source_label"] = "FARS Accident CSV"

                if str(county_code).strip():
                    st.success(
                        f"Loaded {len(crashes_loaded):,} FARS fatal crash points after county/boundary filtering."
                    )
                else:
                    st.success(
                        f"Loaded {len(crashes_loaded):,} FARS fatal crash points before county filtering. Enter a county code to filter the statewide CSV."
                    )

            except Exception as e:
                st.error(
                    f"Unable to read uploaded FARS Accident CSV: {e}"
                )

    crashes_base = st.session_state.get(
        "all_crashes",
        None
    )

    if crashes_base is not None:

        crashes = _render_crash_filters(
            crashes_base,
            source_key="fars" if crash_source == "Use FARS data — no upload" else "upload"
        )

        st.session_state["filtered_crashes"] = crashes
        st.session_state["crashes"] = crashes
        st.session_state["active_map_layer"] = "Crashes"

        st.success(
            f"Crash points loaded after filters: {len(crashes):,}"
        )

    else:
        crashes = st.session_state.get(
            "crashes",
            None
        )

    if crashes is not None:

        crash_color_settings = render_crash_color_controls(
            crashes,
            key_prefix="crash_step_preview",
        )
        if crash_color_settings.get("enabled"):
            field = crash_color_settings.get("field")
            crash_color_settings["color_lookup"] = categorical_color_lookup(
                crashes[field].fillna("Unknown")
            )

        fmap = make_map(
            boundary=selected_boundary,
            roads=selected_roads,
            roads_class=roads_class_display,
            signals=signals_clean,
            corridors=corridors,
            crashes=crashes,
            crash_color_settings=crash_color_settings
        )

        st_folium(
            fmap,
            width=1200,
            height=900,
            key="crash_upload_map"
        )
