"""Step 6 results tables plus orchestration for classification and downloads."""

from .classification import render_classification_step
from .downloads import render_results_downloads
from ..map_symbology import make_numeric_colormap, render_numeric_symbology_controls


def add_density_to_spatial_units(spatial_units_map, np):
    spatial_units_map = spatial_units_map.copy()
    spatial_units_proj = spatial_units_map.to_crs(epsg=3857)

    spatial_units_map["Length_Miles"] = spatial_units_proj.geometry.length / 1609.344
    spatial_units_map["Area_SqMi"] = spatial_units_proj.geometry.area / 2589988.110336
    spatial_units_map["CrashDensity"] = 0.0

    if "UnitType" in spatial_units_map.columns:
        line_mask = spatial_units_map["UnitType"].isin(
            ["Segment", "Corridor", "Sliding Window", "Road Segment"]
        )
        area_mask = spatial_units_map["UnitType"].isin(
            ["Intersection", "Intersection Buffer"]
        )

        spatial_units_map.loc[line_mask, "CrashDensity"] = np.where(
            spatial_units_map.loc[line_mask, "Length_Miles"] > 0,
            spatial_units_map.loc[line_mask, "CrashCount"]
            / spatial_units_map.loc[line_mask, "Length_Miles"],
            0,
        )

        spatial_units_map.loc[area_mask, "CrashDensity"] = np.where(
            spatial_units_map.loc[area_mask, "Area_SqMi"] > 0,
            spatial_units_map.loc[area_mask, "CrashCount"]
            / spatial_units_map.loc[area_mask, "Area_SqMi"],
            0,
        )

        other_mask = ~(line_mask | area_mask)
        spatial_units_map.loc[other_mask, "CrashDensity"] = spatial_units_map.loc[
            other_mask,
            "CrashCount",
        ]
    else:
        geom_types = spatial_units_map.geometry.geom_type
        line_mask = geom_types.isin(["LineString", "MultiLineString"])
        polygon_mask = geom_types.isin(["Polygon", "MultiPolygon"])
        point_mask = geom_types.isin(["Point", "MultiPoint"])

        spatial_units_map.loc[line_mask, "CrashDensity"] = np.where(
            spatial_units_map.loc[line_mask, "Length_Miles"] > 0,
            spatial_units_map.loc[line_mask, "CrashCount"]
            / spatial_units_map.loc[line_mask, "Length_Miles"],
            0,
        )

        spatial_units_map.loc[polygon_mask, "CrashDensity"] = np.where(
            spatial_units_map.loc[polygon_mask, "Area_SqMi"] > 0,
            spatial_units_map.loc[polygon_mask, "CrashCount"]
            / spatial_units_map.loc[polygon_mask, "Area_SqMi"],
            0,
        )

        spatial_units_map.loc[point_mask, "CrashDensity"] = spatial_units_map.loc[
            point_mask,
            "CrashCount",
        ]

    spatial_units_map["CrashDensity"] = (
        spatial_units_map["CrashDensity"]
        .replace([np.inf, -np.inf], 0)
        .fillna(0)
    )

    return spatial_units_map


def make_density_colormap(gdf, pd, cm, density_col="CrashDensity", settings=None):
    values = pd.to_numeric(gdf[density_col], errors="coerce").fillna(0)
    return make_numeric_colormap(
        values,
        cm,
        "Crash Density",
        settings=settings or {
            "method": "Capped gradient",
            "num_classes": 5,
            "cap_percentile": 95,
            "manual_breaks": "",
        },
    )


def render_results_step(st_folium, workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    route_col = st.session_state.get("route_col", "FULLNAME")
    segment_id_col = st.session_state.get("segment_id_col", None)

    render_classification_step(
        workflow_context=workflow_context,
        spatial_unit=spatial_unit,
    )

    spatial_units = st.session_state.get("spatial_units", None)
    assigned_crashes = st.session_state.get("assigned_crashes", None)
    kabco_result = st.session_state.get("kabco_result", None)
    analysis_type = st.session_state.get("analysis_type", None)

    def _analysis_matches_current_workflow(current_spatial_unit, current_analysis_type):
        if current_analysis_type is None:
            return False

        current_analysis_type = str(current_analysis_type).lower()

        if current_spatial_unit == "Intersection":
            return "intersection" in current_analysis_type

        if current_spatial_unit == "Corridor":
            return "corridor" in current_analysis_type

        if current_spatial_unit == "Segment":
            return (
                "segment" in current_analysis_type
                or "road segment" in current_analysis_type
                or "uploaded road segment" in current_analysis_type
            )

        return False

    if spatial_units is not None and assigned_crashes is not None:
        if not _analysis_matches_current_workflow(spatial_unit, analysis_type):
            st.info(
                "Previous results are hidden for this workflow. "
                "Shared inputs like roads, signals, and crashes are still available. "
                "Run this workflow's classification/results step to create new result layers."
            )
            return

    if spatial_units is None or assigned_crashes is None:
        st.info("Classify crashes first to generate results.")
        return

    crash_counts = (
        assigned_crashes
        .groupby("UnitID")
        .size()
        .reset_index(name="CrashCount")
    )

    spatial_units_map = spatial_units.merge(
        crash_counts,
        on="UnitID",
        how="left",
    )

    spatial_units_map["CrashCount"] = (
        spatial_units_map["CrashCount"]
        .fillna(0)
        .astype(int)
    )

    spatial_units_map = add_density_to_spatial_units(spatial_units_map, np)

    with st.expander("Optional minimum crash count filter", expanded=False):
        st.caption(
            "Use this optional filter to remove low-crash spatial units before mapping, "
            "download, and comparison. Leave it off to keep every spatial unit, including "
            "zero-crash units."
        )
        enable_min_crash_filter = st.checkbox(
            "Exclude spatial units with fewer than a minimum number of crashes",
            value=False,
            key=f"results_enable_min_crash_filter_{analysis_type}",
        )
        min_crash_count = st.number_input(
            "Minimum crash count",
            min_value=0,
            value=1,
            step=1,
            key=f"results_min_crash_count_{analysis_type}",
            help=(
                "Editable integer threshold. For example, 1 removes only zero-crash units; "
                "3 keeps units with 3 or more crashes; any other non-negative value can be entered."
            ),
            disabled=not enable_min_crash_filter,
        )

    if enable_min_crash_filter and min_crash_count > 0:
        before_filter_count = len(spatial_units_map)
        spatial_units_map = spatial_units_map[
            spatial_units_map["CrashCount"] >= int(min_crash_count)
        ].copy()
        st.info(
            f"Minimum crash count filter applied: kept {len(spatial_units_map):,} of "
            f"{before_filter_count:,} spatial units with CrashCount >= {int(min_crash_count)}."
        )
        if spatial_units_map.empty:
            st.warning(
                "The minimum crash count filter removed every spatial unit. "
                "Lower the threshold or turn the filter off."
            )

    # Keep the latest computed crash-density layer available for later maps
    # such as the Segment HIN comparison map. The raw spatial_units object
    # may not contain CrashDensity until this step computes it.
    st.session_state["spatial_units_density_map"] = spatial_units_map

    units_table = spatial_units_map.copy()
    units_table["GeometryType"] = units_table.geometry.geom_type

    raw_display_unit_cols = [
        "UnitType",
        "UnitID",
        "IntersectionID",
        "SegmentID",
        "SourceSegmentID",
        "CorridorID",
        "Route",
        route_col,
        segment_id_col,
        "FULLNAME",
        "RoadName1",
        "RoadName2",
        "FromMile",
        "ToMile",
        "Length_Miles",
        "Area_SqMi",
        "CrashCount",
        "CrashDensity",
        "GeometryType",
    ]

    display_unit_cols = []
    for c in raw_display_unit_cols:
        if c is not None and c in units_table.columns and c not in display_unit_cols:
            display_unit_cols.append(c)

    units_table = units_table[display_unit_cols]

    assigned_table = assigned_crashes.copy()
    assigned_table["Latitude"] = assigned_table.geometry.y
    assigned_table["Longitude"] = assigned_table.geometry.x

    raw_display_crash_cols = [
        "CrashID",
        "SourceCrashID",
        "UnitType",
        "UnitID",
        "IntersectionID",
        "SegmentID",
        "CorridorID",
        "Route",
        route_col,
        segment_id_col,
        "FULLNAME",
        "Latitude",
        "Longitude",
        "DistToUnit_M",
        "KABCO",
        "kabco",
        "Severity",
        "severity",
        "CRASH_SEVERITY",
        "Crash Severity",
        "INJURY_SEVERITY",
        "injury_severity",
    ]

    display_crash_cols = []
    for c in raw_display_crash_cols:
        if c is not None and c in assigned_table.columns and c not in display_crash_cols:
            display_crash_cols.append(c)

    assigned_table = assigned_table[display_crash_cols]

    density_symbology_settings = render_numeric_symbology_controls(
        "Crash density",
        key_prefix=f"results_crash_density_{analysis_type}",
        default_method="Capped gradient",
    )

    density_cmap = make_density_colormap(
        spatial_units_map,
        pd,
        cm,
        settings=density_symbology_settings,
    )

    render_results_downloads(
        st_folium=st_folium,
        workflow_context=workflow_context,
        spatial_units_map=spatial_units_map,
        units_table=units_table,
        assigned_table=assigned_table,
        assigned_crashes=assigned_crashes,
        kabco_result=kabco_result,
        analysis_type=analysis_type,
        density_cmap=density_cmap,
    )
