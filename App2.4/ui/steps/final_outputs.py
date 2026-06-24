from ui.map_view import make_json_safe_gdf
from modules.sliding_window import section7_excel_bytes
from .sliding_window import _ensure_hin_priority_columns

"""Final results tables and downloads.

This section shows saved result tables and downloads after analysis runs. It
keeps original analysis outputs separate from visualization filters.
"""


def _csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")


def _geojson_bytes(gdf):
    safe = make_json_safe_gdf(gdf.to_crs(4326))
    return safe.to_json().encode("utf-8")


def _table_with_rank(df, rank_cols):
    out = df.copy()
    for col in rank_cols:
        if col in out.columns:
            out = out.sort_values(col, ascending=False).copy()
            out.insert(0, "Rank", range(1, len(out) + 1))
            return out
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out


def _drop_geometry(gdf_or_df):
    return gdf_or_df.drop(columns="geometry", errors="ignore")


def _render_corridor_downloads(st):
    corridors_all = st.session_state.get("corridors", None)
    corridors_filtered = st.session_state.get("final_corridors", None)

    if corridors_all is None and corridors_filtered is None:
        return

    st.markdown("**Corridors**")

    col1, col2 = st.columns(2)
    with col1:
        if corridors_all is not None and not getattr(corridors_all, "empty", True):
            table_all = _table_with_rank(_drop_geometry(corridors_all), ["CrashDensity", "CrashCount", "SignalCnt"])
            with st.expander("All generated corridors table", expanded=False):
                st.dataframe(table_all, width="stretch", hide_index=True)
            st.download_button(
                "Download all generated corridors CSV",
                data=_csv_bytes(table_all),
                file_name="all_generated_corridors.csv",
                mime="text/csv",
                key="final_download_all_corridors_csv",
            )
            st.download_button(
                "Download all generated corridors GeoJSON",
                data=_geojson_bytes(corridors_all),
                file_name="all_generated_corridors.geojson",
                mime="application/geo+json",
                key="final_download_all_corridors_geojson",
            )

    with col2:
        if corridors_filtered is not None and not getattr(corridors_filtered, "empty", True):
            table_filtered = _table_with_rank(_drop_geometry(corridors_filtered), ["CrashDensity", "CrashCount", "SignalCnt"])
            with st.expander("Filtered corridors table", expanded=False):
                st.dataframe(table_filtered, width="stretch", hide_index=True)
            st.download_button(
                "Download filtered corridors CSV",
                data=_csv_bytes(table_filtered),
                file_name="filtered_corridors.csv",
                mime="text/csv",
                key="final_download_filtered_corridors_csv",
            )
            st.download_button(
                "Download filtered corridors GeoJSON",
                data=_geojson_bytes(corridors_filtered),
                file_name="filtered_corridors.geojson",
                mime="application/geo+json",
                key="final_download_filtered_corridors_geojson",
            )


def _render_crash_density_downloads(st):
    spatial_units = st.session_state.get("spatial_units_density_map", None)
    if spatial_units is None or getattr(spatial_units, "empty", True):
        return

    st.markdown("**Crash density results**")
    rank_cols = ["CrashDensity", "CrashCount", "EPDO", "KSI_Count", "Fatal_Injury_Count"]
    table = _table_with_rank(_drop_geometry(spatial_units), rank_cols)
    with st.expander("Crash density table", expanded=False):
        st.dataframe(table, width="stretch", hide_index=True)

    st.download_button(
        "Download crash density CSV",
        data=_csv_bytes(table),
        file_name="crash_density_results.csv",
        mime="text/csv",
        key="final_download_crash_density_csv",
    )
    st.download_button(
        "Download crash density GeoJSON",
        data=_geojson_bytes(spatial_units),
        file_name="crash_density_results.geojson",
        mime="application/geo+json",
        key="final_download_crash_density_geojson",
    )


def _render_hin_downloads(st):
    results = st.session_state.get("section7_results", None)
    if results is None:
        return

    st.markdown("**HIN sliding-window results**")

    risk_segments = _ensure_hin_priority_columns(results["risk_segments"])
    risk_windows = results.get("risk_windows", None)
    risk_corridors = results.get("risk_corridors", None)

    seg_table = _table_with_rank(
        _drop_geometry(risk_segments),
        ["HIN_Priority_Index", "Max_Window_Score", "EPDO", "Crash_Count"],
    )
    with st.expander("HIN risk segment table", expanded=True):
        st.dataframe(seg_table, width="stretch", hide_index=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "Download HIN risk segments CSV",
            data=_csv_bytes(seg_table),
            file_name="hin_risk_segments.csv",
            mime="text/csv",
            key="final_download_hin_segments_csv",
        )
    with c2:
        st.download_button(
            "Download HIN risk segments GeoJSON",
            data=_geojson_bytes(risk_segments),
            file_name="hin_risk_segments.geojson",
            mime="application/geo+json",
            key="final_download_hin_segments_geojson",
        )
    with c3:
        st.download_button(
            "Download HIN results Excel",
            data=section7_excel_bytes(risk_windows, risk_segments, risk_corridors),
            file_name="hin_sliding_window_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="final_download_hin_excel",
        )

    if risk_windows is not None and not getattr(risk_windows, "empty", True):
        win_table = _table_with_rank(
            _drop_geometry(risk_windows),
            ["Window_Score", "EPDO", "Crash_Count"],
        )
        with st.expander("Sliding-window table", expanded=False):
            st.dataframe(win_table, width="stretch", hide_index=True)
        st.download_button(
            "Download sliding-window table CSV",
            data=_csv_bytes(win_table),
            file_name="sliding_window_table.csv",
            mime="text/csv",
            key="final_download_hin_windows_csv",
        )

    if risk_corridors is not None and not getattr(risk_corridors, "empty", True):
        corridor_table = _table_with_rank(
            _drop_geometry(risk_corridors),
            ["Max_HIN_Index", "HIN_Priority_Index", "Crash_Count"],
        )
        with st.expander("HIN corridor table", expanded=False):
            st.dataframe(corridor_table, width="stretch", hide_index=True)
        st.download_button(
            "Download HIN corridors CSV",
            data=_csv_bytes(corridor_table),
            file_name="hin_corridors.csv",
            mime="text/csv",
            key="final_download_hin_corridors_csv",
        )


def render_final_outputs_step(workflow_context, spatial_unit=None):
    globals().update(workflow_context)

    has_any = (
        st.session_state.get("spatial_units_density_map", None) is not None
        or st.session_state.get("section7_results", None) is not None
        or st.session_state.get("corridors", None) is not None
        or st.session_state.get("final_corridors", None) is not None
    )

    if not has_any:
        st.info("Run the workflow first. Tables and download buttons will appear here after results are created.")
        return

    if st.button("Open dashboard", type="primary", key="open_results_dashboard"):
        st.session_state["dashboard_mode"] = True
        st.rerun()

    _render_crash_density_downloads(st)
    _render_hin_downloads(st)
    _render_corridor_downloads(st)
