"""Dashboard-style result explorer with chart, table, and map blocks.

The dashboard is for decision makers. It focuses on crash patterns,
spatial-unit rankings, crash-density/HIN outputs, and selected read-only map
views. It does not overwrite workflow results.
"""

import io
import re
import html
import base64
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.io as pio

try:
    import geopandas as gpd
except Exception:  # pragma: no cover
    gpd = None

try:
    import folium
    from folium.features import GeoJsonTooltip
    from streamlit_folium import st_folium
except Exception:  # pragma: no cover
    folium = None
    GeoJsonTooltip = None
    st_folium = None

try:
    from docx import Document
    from docx.shared import Inches
except Exception:  # pragma: no cover
    Document = None
    Inches = None


def _drop_geometry(df):
    return df.drop(columns="geometry", errors="ignore") if df is not None else None


def _safe_scalar(value):
    """Make values safe for Streamlit Arrow, JSON, HTML, and Word export."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(value, "isoformat") and value.__class__.__name__ in ["date", "datetime", "time"]:
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, (list, tuple, set, dict)):
        return str(value)
    return value


def _safe_dataframe_for_display(df):
    """Return a copy that Streamlit can display without pyarrow mixed-type errors."""
    if df is None:
        return pd.DataFrame()
    out = _drop_geometry(df).copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        elif out[col].dtype == "object":
            out[col] = out[col].map(_safe_scalar)
            # Mixed object columns, such as Location containing text and ints,
            # trigger ArrowTypeError. String conversion is safer for dashboard UI.
            out[col] = out[col].astype(str).replace({"None": "", "nan": "", "NaT": ""})
    return out


def _safe_geojson_gdf(gdf):
    """Return GeoDataFrame with JSON-safe attributes and Leaflet-safe geometry.

    TIGER and uploaded layers sometimes contain empty geometry, GeometryCollection,
    or mixed object/date attributes. Folium/streamlit-folium can fail when a
    GeoJSON feature does not have a simple ``coordinates`` member, so this
    helper explodes multipart features and removes empty/unsupported geometry.
    """
    if gdf is None:
        return gdf
    work = gdf.copy()
    if gpd is not None and not isinstance(work, gpd.GeoDataFrame):
        try:
            work = gpd.GeoDataFrame(work, geometry="geometry")
        except Exception:
            return gdf
    if "geometry" not in work.columns:
        return work
    try:
        work = work[work.geometry.notna() & (~work.geometry.is_empty)].copy()
    except Exception:
        pass
    try:
        # Split multipart roads/corridors; ignore index so Folium ids are simple.
        work = work.explode(index_parts=False, ignore_index=True)
    except Exception:
        pass
    try:
        # Folium's get_bounds handles Point/LineString/Polygon/Multi* well, but
        # GeometryCollection can trigger KeyError: 'coordinates'.
        ok_types = {
            "Point", "MultiPoint", "LineString", "MultiLineString",
            "Polygon", "MultiPolygon"
        }
        work = work[work.geometry.geom_type.isin(ok_types)].copy()
    except Exception:
        pass
    for col in list(work.columns):
        if col == "geometry":
            continue
        try:
            if pd.api.types.is_datetime64_any_dtype(work[col]):
                work[col] = work[col].dt.strftime("%Y-%m-%d %H:%M:%S")
            elif work[col].dtype == "object":
                work[col] = work[col].map(_safe_scalar)
                work[col] = work[col].astype(str).replace({"None": "", "nan": "", "NaT": ""})
        except Exception:
            work[col] = work[col].astype(str)
    return work


def _safe_geojson_string(gdf):
    """Convert a GeoDataFrame to a GeoJSON string, returning None on failure."""
    try:
        clean = _safe_geojson_gdf(gdf)
        if clean is None or getattr(clean, "empty", True):
            return None
        return clean.to_json()
    except Exception:
        return None

def _polish_figure(fig):
    """Use a clean web-app palette for screen and exports."""
    try:
        fig.update_layout(
            template="plotly_white",
            colorway=["#2563eb", "#16a34a", "#f97316", "#dc2626", "#7c3aed", "#0891b2", "#ca8a04", "#475569"],
            font=dict(color="#1f2937"),
            paper_bgcolor="white",
            plot_bgcolor="white",
        )
        for i, trace in enumerate(fig.data):
            t = getattr(trace, "type", "")
            marker = getattr(trace, "marker", None)
            if t == "bar" and marker is not None:
                current = getattr(marker, "color", None)
                if current is None or str(current).lower().startswith("#0000") or str(current).lower() in ["black", "#000000"]:
                    marker.color = ["#2563eb", "#16a34a", "#f97316", "#dc2626", "#7c3aed", "#0891b2"][i % 6]
            elif t == "pie" and marker is not None:
                marker.colors = ["#2563eb", "#16a34a", "#f97316", "#dc2626", "#7c3aed", "#0891b2", "#ca8a04", "#64748b", "#94a3b8", "#0f766e"]
            elif t in ["scatter"] and marker is not None:
                marker.color = "#2563eb"
    except Exception:
        pass
    return fig


def _safe_name(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_") or "data"



def _enrich_assigned_crashes(st):
    """Return assigned crashes with original crash attributes when IDs match.

    Some workflow tables keep only assignment fields. Dashboard summaries need the
    original crash type/year/severity/reason fields, so we merge them back when a
    common crash ID is available. If no match is possible, the assigned table is
    returned unchanged.
    """
    assigned = st.session_state.get("assigned_crashes")
    crashes = st.session_state.get("crashes")
    if assigned is None:
        return None
    assigned_df = _drop_geometry(assigned).copy()
    if crashes is None:
        return assigned_df
    crash_df = _drop_geometry(crashes).copy()
    candidates = ["CrashID", "SourceCrashID", "CRASH_ID", "OBJECTID", "CaseID", "CrashNumber"]
    for key in candidates:
        if key in assigned_df.columns and key in crash_df.columns:
            add_cols = [c for c in crash_df.columns if c not in assigned_df.columns or c == key]
            try:
                return assigned_df.merge(crash_df[add_cols], on=key, how="left", suffixes=("", "_src"))
            except Exception:
                return assigned_df
    return assigned_df

def _available_tables(st):
    tables = {}

    if st.session_state.get("crashes") is not None:
        tables["Uploaded crashes"] = _drop_geometry(st.session_state["crashes"])

    assigned_enriched = _enrich_assigned_crashes(st)
    if assigned_enriched is not None:
        tables["Assigned crashes"] = assigned_enriched

    if st.session_state.get("spatial_units_density_map") is not None:
        tables["Crash density results"] = _drop_geometry(st.session_state["spatial_units_density_map"])

    if st.session_state.get("kabco_result") is not None:
        tables["Crash count / severity summary"] = _drop_geometry(st.session_state["kabco_result"])

    if st.session_state.get("section7_results") is not None:
        results = st.session_state["section7_results"]
        if results.get("risk_segments") is not None:
            tables["HIN risk segments"] = _drop_geometry(results["risk_segments"])
        if results.get("risk_windows") is not None:
            tables["Sliding windows"] = _drop_geometry(results["risk_windows"])
        if results.get("risk_corridors") is not None:
            tables["HIN corridors"] = _drop_geometry(results["risk_corridors"])

    if st.session_state.get("corridors") is not None:
        tables["Generated corridors"] = _drop_geometry(st.session_state["corridors"])

    if st.session_state.get("final_corridors") is not None:
        tables["Filtered corridors"] = _drop_geometry(st.session_state["final_corridors"])

    return {
        name: table
        for name, table in tables.items()
        if table is not None and not getattr(table, "empty", True)
    }


def _fallback_crs_from_session(st):
    """Find a trusted CRS from workflow layers when a result layer lost CRS."""
    for key in [
        "selected_roads",
        "corridor_roads",
        "selected_boundary",
        "spatial_units",
        "corridors",
        "final_corridors",
    ]:
        layer = st_obj.session_state.get(key) if st_obj is not None else None
        if layer is not None and hasattr(layer, "crs") and layer.crs is not None:
            return layer.crs
    return "EPSG:4326"


def _repair_gdf_crs(gdf, st=None):
    """Return a GeoDataFrame with a usable CRS for dashboard maps.

    Some workflow result copies can lose CRS. If their coordinates are outside
    longitude/latitude range, setting EPSG:4326 directly makes the dashboard map
    zoom to the world. In that case, use the road/boundary CRS from session when
    available before converting to web map coordinates.
    """
    if gdf is None or getattr(gdf, "empty", True) or not hasattr(gdf, "geometry"):
        return gdf
    work = gdf.copy()
    try:
        bounds = work.total_bounds
        looks_lonlat = (
            -180 <= float(bounds[0]) <= 180
            and -90 <= float(bounds[1]) <= 90
            and -180 <= float(bounds[2]) <= 180
            and -90 <= float(bounds[3]) <= 90
        )
    except Exception:
        looks_lonlat = True
    if work.crs is None:
        if looks_lonlat:
            work = work.set_crs(epsg=4326)
        else:
            fallback = _fallback_crs_from_session(st) if st is not None else "EPSG:4326"
            work = work.set_crs(fallback)
    return work


def _available_maps(st):
    maps = {}
    density = st.session_state.get("spatial_units_density_map")
    if density is not None and not getattr(density, "empty", True):
        maps["Crash density map"] = _repair_gdf_crs(density, st)

    results = st.session_state.get("section7_results")
    if results is not None:
        risk_segments = results.get("risk_segments")
        if risk_segments is not None and not getattr(risk_segments, "empty", True):
            maps["HIN priority map"] = _repair_gdf_crs(risk_segments, st)

    corridors = st.session_state.get("final_corridors", st.session_state.get("corridors"))
    if corridors is not None and not getattr(corridors, "empty", True):
        maps["Corridor map"] = _repair_gdf_crs(corridors, st)

    return maps


def _numeric_cols(df):
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _groupable_cols(df):
    cols = []
    n = max(len(df), 1)
    max_unique = max(30, min(250, int(n * 0.45)))
    important_words = [
        "type", "year", "month", "date", "time", "severity", "kabco",
        "unit", "route", "corridor", "segment", "intersection", "road",
        "manner", "weather", "light", "surface", "reason", "cause",
        "class", "injury", "crash", "collision", "factor", "direction",
    ]
    for col in df.columns:
        if col == "geometry":
            continue
        lower = str(col).lower()
        nunique = df[col].nunique(dropna=True)
        if any(word in lower for word in important_words):
            cols.append(col)
        elif not pd.api.types.is_numeric_dtype(df[col]):
            try:
                if df[col].astype(str).str.len().mean() <= 100:
                    cols.append(col)
            except Exception:
                cols.append(col)
        elif nunique <= max_unique:
            cols.append(col)
    seen = set()
    out = []
    for c in cols:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def _find_col(df, keywords):
    for col in df.columns:
        lower = str(col).lower()
        if all(k in lower for k in keywords):
            return col
    for col in df.columns:
        lower = str(col).lower()
        if any(k in lower for k in keywords):
            return col
    return None


def _default_metric(num_cols):
    preferred = [
        "HIN_Priority_Index", "RiskScore", "CrashDensity", "CrashDensity_per_mile",
        "Crash_Count", "CrashCount", "TotalCrashes", "EPDO", "KSI_Count",
        "Fatal_Injury_Count", "Total",
    ]
    for col in preferred:
        if col in num_cols:
            return col
    return num_cols[0] if num_cols else None


def _rank_table(df, metric=None):
    out = df.copy()
    if metric and metric in out.columns:
        out = out.sort_values(metric, ascending=False).copy()
    if "Rank" not in out.columns:
        out.insert(0, "Rank", range(1, len(out) + 1))
    return out


def _aggregate(df, group_col, metric, aggregation, top_n):
    if not group_col:
        return pd.DataFrame()
    work = df.copy()
    work[group_col] = work[group_col].fillna("Unknown").astype(str)

    if aggregation == "Count" or metric is None or metric not in work.columns:
        out = work.groupby(group_col, dropna=False).size().reset_index(name="Count")
        value_col = "Count"
    else:
        work["__metric__"] = pd.to_numeric(work[metric], errors="coerce")
        agg_map = {
            "Sum": "sum",
            "Average": "mean",
            "Mean": "mean",
            "Median": "median",
            "Minimum": "min",
            "Maximum": "max",
        }
        agg_func = agg_map.get(aggregation, "sum")
        out = work.groupby(group_col, dropna=False)["__metric__"].agg(agg_func).reset_index()
        value_col = f"{aggregation} {metric}"
        out = out.rename(columns={"__metric__": value_col})

    out = out.sort_values(value_col, ascending=False).head(top_n).reset_index(drop=True)
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out




def _rank_units_for_chart(df, metric, top_n=15):
    """Rank existing spatial-unit rows without summing the metric.

    Crash-density/HIN result tables already have one row per spatial unit. Using
    groupby-sum can create labels like "Sum CrashDensity" and can accidentally
    group by a numeric length field. This helper keeps the original unit ID and
    ranks by the selected metric directly.
    """
    if df is None or getattr(df, "empty", True) or metric not in df.columns:
        return pd.DataFrame(), None, None
    unit_col = _unit_col(df)
    work = df.copy()
    if unit_col is None:
        unit_col = "DashboardUnitID"
        work[unit_col] = [f"UNIT_{i + 1}" for i in range(len(work))]
    else:
        lower_unit = str(unit_col).lower()
        if any(bad in lower_unit for bad in ["length", "mile", "density", "count", "score", "index"]):
            unit_col = "DashboardUnitID"
            work[unit_col] = [f"UNIT_{i + 1}" for i in range(len(work))]
    work[metric] = pd.to_numeric(work[metric], errors="coerce").fillna(0)
    work[unit_col] = work[unit_col].astype(str)
    keep_cols = [unit_col, metric]
    for extra in ["CrashCount", "Crash_Count", "UnitType", "City", "Length_Miles", "Length_mi", "Route", "FULLNAME", "RoadName", "RoadName1", "RoadName2", "CorridorID"]:
        if extra in work.columns and extra not in keep_cols:
            keep_cols.append(extra)
    out = work[keep_cols].sort_values(metric, ascending=False).head(top_n).reset_index(drop=True)
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out, unit_col, metric


def _nice_metric_label(metric):
    labels = {
        "CrashDensity": "Crash density",
        "CrashDensity_per_mile": "Crash density",
        "CrashCount": "Crash count",
        "Crash_Count": "Crash count",
        "HIN_Priority_Index": "HIN priority index",
        "RiskScore": "Risk score",
    }
    return labels.get(str(metric), str(metric).replace("_", " "))

def _style(st):
    st.markdown(
        """
        <style>
        /* Dashboard mode uses one internal scroll area only.
           Without this, Streamlit shows both the browser/page scrollbar and
           the tab-panel scrollbar. */
        html, body, .stApp, [data-testid="stAppViewContainer"],
        [data-testid="stMain"], section[data-testid="stMain"],
        .main, .block-container {
            height: 100vh !important;
            max-height: 100vh !important;
            overflow-y: hidden !important;
            overflow-x: hidden !important;
        }
        .block-container { padding-top: .65rem; padding-bottom: .75rem !important; max-width: 1900px; }
        [data-testid="stVerticalBlock"] { overflow: visible !important; }
        .dashboard-scroll-note { color:#64748b; font-size:.86rem; margin-top:-.2rem; margin-bottom:.4rem; }
        .dashboard-hero {
            border-radius: 18px;
            padding: 1.0rem 1.2rem;
            background: linear-gradient(135deg, #f8fafc 0%, #edf5f1 100%);
            border: 1px solid #dbe7e1;
            margin-bottom: .9rem;
        }
        .dashboard-hero h1 { margin: 0 0 .25rem 0; letter-spacing: -0.03em; font-size: 1.55rem; }
        .dashboard-hero p { margin: 0; max-width: 980px; color: #52615a; }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e3e8e5;
            padding: .75rem .9rem;
            border-radius: 15px;
            box-shadow: 0 8px 22px rgba(15, 43, 33, .055);
        }
        .dashboard-card {
            background: #ffffff;
            border: 1px solid #e3e8e5;
            border-radius: 16px;
            padding: 1rem;
            margin-bottom: .75rem;
        }
        .dashboard-section-title {
            font-size: 1.38rem;
            font-weight: 750;
            letter-spacing: -0.02em;
            padding: .3rem 0 .45rem 0;
            margin: .55rem 0 .4rem 0;
            border-bottom: 1px solid #e6ece8;
        }
        .dashboard-section-title span {
            color: #4a5b53;
            font-size: .88rem;
            font-weight: 450;
            margin-left: .45rem;
        }
        .small-muted { color: #62716a; font-size: .9rem; }
        .dashboard-chart-card {
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: .55rem .6rem .25rem .6rem;
            margin-bottom: .75rem;
            background: white;
        }
        .stTabs [data-baseweb="tab-panel"] {
            max-height: calc(100vh - 165px) !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            padding-right: 12px !important;
            padding-bottom: 4rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _metric_cards(st, tables):
    analysis_type = st.session_state.get("analysis_type", st.session_state.get("spatial_unit", "Spatial Unit"))
    crashes = tables.get("Assigned crashes", tables.get("Uploaded crashes"))
    density = tables.get("Crash density results")
    hin = tables.get("HIN risk segments", tables.get("HIN corridors"))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Crash records", f"{len(crashes):,}" if crashes is not None else "0")
    with c2:
        if crashes is not None:
            year_col = _find_col(crashes, ["year"])
            if year_col:
                years = pd.to_numeric(crashes[year_col], errors="coerce").dropna()
                label = f"{int(years.min())}–{int(years.max())}" if not years.empty else "Not found"
            else:
                label = "Not found"
            st.metric("Crash years", label)
        else:
            st.metric("Crash years", "Not available")
    with c3:
        if density is not None and "CrashDensity" in density.columns:
            st.metric("Avg crash density", f"{pd.to_numeric(density['CrashDensity'], errors='coerce').mean():,.2f}")
        elif density is not None and "CrashCount" in density.columns:
            st.metric("Avg crash count", f"{pd.to_numeric(density['CrashCount'], errors='coerce').mean():,.2f}")
        else:
            st.metric("Crash density", "Run crash density")
    with c4:
        if str(analysis_type).lower().startswith("intersection") and hin is None:
            st.metric("Risk method", "Crash count/density")
            st.caption("Intersection workflow does not use Sliding Window HIN.")
        elif hin is not None:
            metric = _default_metric(_numeric_cols(hin))
            if metric:
                top = pd.to_numeric(hin[metric], errors="coerce").max()
                st.metric("Highest risk value", f"{top:,.2f}")
            else:
                st.metric("Highest risk value", "Not available")
        else:
            st.metric("Risk method", "Run HIN")



def _unit_col(df):
    """Find a readable spatial-unit identifier column.

    Important: choose ID columns before loose words like "segment". In the
    segment workflow, columns such as SegmentLength_Mile contain the word
    "segment" but are numeric measures, not IDs. This function prevents those
    fields from appearing as the ranking y-axis.
    """
    if df is None:
        return None
    exact_priority = [
        "UnitID", "SpatialUnitID", "RiskSegmentID", "WindowID", "SegmentID", "SourceSegmentID",
        "IntersectionID", "CorridorID", "CorridorID_Final", "FeatureID", "ObjectID",
        "Route", "FULLNAME", "RoadName", "Name",
    ]
    norm = {str(c).lower().replace("_", "").replace(" ", ""): c for c in df.columns}
    for wanted in exact_priority:
        key = wanted.lower().replace("_", "").replace(" ", "")
        if key in norm:
            return norm[key]

    # Prefer text/object ID-like fields. Avoid length/mile/density/count fields.
    bad_words = ["length", "mile", "density", "count", "area", "score", "index", "risk", "rank"]
    for c in df.columns:
        lower = str(c).lower()
        if any(bad in lower for bad in bad_words):
            continue
        if lower.endswith("id") or any(w in lower for w in ["unit", "intersection", "corridor", "route", "roadname"]):
            return c
    return None


def _crash_type_col(df):
    if df is None:
        return None
    return (
        _find_col(df, ["crash", "type"])
        or _find_col(df, ["collision", "type"])
        or _find_col(df, ["manner"])
        or _find_col(df, ["type"])
        or _find_col(df, ["kabco"])
        or _find_col(df, ["severity"])
    )




def _kabco_col(df):
    """Find the KABCO / injury severity column when present."""
    if df is None:
        return None
    for col in df.columns:
        lower = str(col).lower().replace("_", "")
        if lower == "kabco" or "kabco" in lower:
            return col
    for col in df.columns:
        lower = str(col).lower()
        if "severity" in lower or "injury" in lower:
            return col
    return None


def _order_kabco(df, kabco_col):
    """Sort KABCO values in engineering severity order when possible."""
    if df is None or kabco_col not in df.columns:
        return df
    order = {"K": 1, "A": 2, "B": 3, "C": 4, "O": 5, "PDO": 5, "UNKNOWN": 9}
    out = df.copy()
    out["__kabco_order__"] = out[kabco_col].astype(str).str.upper().map(order).fillna(8)
    out = out.sort_values(["__kabco_order__", kabco_col]).drop(columns="__kabco_order__")
    return out

def _crash_count_col(df):
    if df is None:
        return None
    preferred = ["CrashCount", "Crash_Count", "TotalCrashes", "CrashCnt", "Crashes", "Count"]
    for c in preferred:
        if c in df.columns:
            return c
    for c in df.columns:
        lower = str(c).lower().replace("_", "")
        if "crash" in lower and ("count" in lower or "cnt" in lower or "total" in lower):
            return c
    return None


def _road_class_col(df):
    """Road-class helper used only as a fallback after the user-selected filter column."""
    if df is None:
        return None
    preferred = [
        "RoadClassFilterCol", "RoadClassFilterValues", "RoadStyleClass",
        "FunctionalClass", "RoadClass", "RoadType", "Functional_Class",
        "Road_Type", "RoadType", "F_SYSTEM", "FUNC_CLASS", "MTFCC", "highway"
    ]
    norm = {str(c).lower().replace("_", "").replace(" ", ""): c for c in df.columns}
    for p in preferred:
        key = p.lower().replace("_", "").replace(" ", "")
        if key in norm:
            return norm[key]
    for c in df.columns:
        lower = str(c).lower()
        if ("road" in lower and ("class" in lower or "type" in lower)) or "functional" in lower:
            return c
    return None


def _active_road_class_column(st_obj=None):
    """Return the exact road-class column selected in Step 1, if the filter is active."""
    try:
        if st_obj is None:
            return None
        if not bool(st_obj.session_state.get("road_class_layer_enabled", False)):
            return None
        col = st_obj.session_state.get("analysis_road_class_col") or st_obj.session_state.get("road_class_viz_col")
        if col is None or str(col).strip() == "":
            return None
        return str(col)
    except Exception:
        return None


def _apply_selected_road_classes(work, class_col, st_obj=None):
    selected = (st_obj.session_state.get("analysis_road_class_values") or st_obj.session_state.get("road_class_viz_values")) if st_obj is not None else None
    if selected and class_col in work.columns:
        selected_text = {str(v) for v in selected}
        work = work[work[class_col].astype(str).isin(selected_text)].copy()
    return work


def _road_class_summary_table(crashes=None, density=None, roads=None, top_n=15, st_obj=None):
    """Create road-class chart only when the Step 1 road-class filter is enabled.

    This avoids misleading charts from unrelated fields such as OSM signal
    ``highway=traffic_signals``. The chart uses the exact column selected by the
    user in Step 1; if crash counts are not joined to that field, it falls back to
    total selected roadway length by that same field.
    """
    class_col = _active_road_class_column(st_obj)
    if not class_col:
        return None, pd.DataFrame(), None, None

    candidates = []
    if density is not None and not getattr(density, "empty", True):
        candidates.append(("density", density))
    if crashes is not None and not getattr(crashes, "empty", True):
        candidates.append(("crashes", crashes))
    # Prefer the Step 1 selected/display road network for roadway length context.
    for key in ["roads_class_display", "selected_roads", "analysis_roads"]:
        layer = st_obj.session_state.get(key) if st_obj is not None else None
        if layer is not None and not getattr(layer, "empty", True):
            candidates.append(("roads", layer))

    for kind, df in candidates:
        work = _drop_geometry(df).copy()
        use_col = class_col if class_col in work.columns else None
        if use_col is None and class_col == "RoadStyleClass" and "RoadStyleClass" in work.columns:
            use_col = "RoadStyleClass"
        if use_col is None:
            continue
        work = _apply_selected_road_classes(work, use_col, st_obj)
        if work.empty:
            continue
        count_col = _crash_count_col(work)
        length_col = _normal_col(work, ["Length_Miles", "Length_Mi", "length_mi", "Miles", "SegmentLength_Mile"])
        if count_col and count_col in work.columns:
            work[count_col] = pd.to_numeric(work[count_col], errors="coerce").fillna(0)
            out = work.groupby(use_col, dropna=False)[count_col].sum().reset_index(name="Crash count")
            value_col = "Crash count"
            title = f"Crashes by road class ({use_col})"
        elif kind == "roads" and length_col and length_col in work.columns:
            work[length_col] = pd.to_numeric(work[length_col], errors="coerce").fillna(0)
            out = work.groupby(use_col, dropna=False)[length_col].sum().reset_index(name="Total length (mi)")
            value_col = "Total length (mi)"
            title = f"Roadway length by road class ({use_col})"
        elif kind == "roads":
            out = work.groupby(use_col, dropna=False).size().reset_index(name="Road feature count")
            value_col = "Road feature count"
            title = f"Road features by road class ({use_col})"
        else:
            continue
        out[use_col] = out[use_col].astype(str).replace({"nan": "Unknown", "None": "Unknown", "": "Unknown"})
        out = out.sort_values(value_col, ascending=False).head(top_n).reset_index(drop=True)
        out.insert(0, "Rank", range(1, len(out) + 1))
        return title, out, use_col, value_col

    return None, pd.DataFrame(), None, None

def _chart_height():
    # Compact height so the dashboard page can show more charts without feeling cut off.
    return 280


def _render_pattern_charts(st, tables):
    crashes = tables.get("Assigned crashes", tables.get("Uploaded crashes"))
    density = tables.get("Crash density results")
    hin = tables.get("HIN risk segments", tables.get("HIN corridors"))

    st.markdown("<div class='dashboard-section-title'>Crash patterns <span>years, crash type, severity, and contributing fields</span></div>", unsafe_allow_html=True)
    left, right = st.columns(2)

    with left:
        if crashes is not None:
            year_col = _find_col(crashes, ["year"])
            if year_col:
                year_df = _aggregate(crashes, year_col, None, "Count", 20)
                fig = px.bar(year_df.sort_values(year_col), x=year_col, y="Count", title="Crashes by year")
                fig.update_layout(height=_chart_height(), margin=dict(l=20, r=20, t=45, b=35))
                st.plotly_chart(_polish_figure(fig), width="stretch")
            else:
                st.info("No crash year field was detected.")
        else:
            st.info("No crash table is available yet.")

    with right:
        if crashes is not None:
            type_col = _crash_type_col(crashes)
            if type_col:
                type_df = _aggregate(crashes, type_col, None, "Count", 10)
                # Use a donut chart for crash type because it is a part-to-whole question.
                fig = px.pie(type_df, names=type_col, values="Count", hole=0.38, title=f"Crash type share by {type_col}")
                fig.update_layout(height=_chart_height(), margin=dict(l=20, r=20, t=45, b=35), legend=dict(orientation="v"))
                st.plotly_chart(_polish_figure(fig), width="stretch")
            else:
                st.info("No crash type/severity field was detected.")
        else:
            st.info("No crash table is available yet.")

    if crashes is not None:
        kabco_col = _kabco_col(crashes)
        if kabco_col:
            kabco_df = _aggregate(crashes, kabco_col, None, "Count", 10)
            kabco_df = _order_kabco(kabco_df, kabco_col)
            fig = px.bar(kabco_df, x=kabco_col, y="Count", title=f"KABCO / severity distribution by {kabco_col}")
            fig.update_layout(height=300, margin=dict(l=20, r=20, t=45, b=35))
            st.plotly_chart(_polish_figure(fig), width="stretch")

    road_title, road_df, road_class_col, road_value_col = _road_class_summary_table(crashes=crashes, density=density, roads=st.session_state.get("selected_roads"), st_obj=st)
    if road_title and not road_df.empty:
        fig = px.bar(road_df, y=road_class_col, x=road_value_col, orientation="h", title=road_title)
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=45, b=35), yaxis_title="Road class", xaxis_title=road_value_col)
        st.plotly_chart(_polish_figure(fig), width="stretch")

    st.markdown("<div class='dashboard-section-title'>Risk and spatial-unit ranking <span>crash density and crash count ranking</span></div>", unsafe_allow_html=True)
    left, right = st.columns(2)

    with left:
        if density is not None:
            metric = "CrashDensity" if "CrashDensity" in density.columns else _default_metric(_numeric_cols(density))
            rank_df, unit_col, value_col = _rank_units_for_chart(density, metric, 15) if metric else (pd.DataFrame(), None, None)
            if not rank_df.empty:
                fig = px.bar(rank_df, y=unit_col, x=value_col, orientation="h", title="Top spatial units by crash density")
                fig.update_layout(
                    height=_chart_height(),
                    margin=dict(l=20, r=20, t=45, b=35),
                    yaxis={"categoryorder": "total ascending", "title": "Spatial unit ID"},
                    xaxis_title="Crash density",
                )
                st.plotly_chart(_polish_figure(fig), width="stretch")
            else:
                st.info("Run crash-density analysis to rank spatial units.")
        else:
            st.info("Crash-density results are not available yet. Run crash-density analysis first.")

    with right:
        if density is not None:
            count_col = _crash_count_col(density)
            rank_df, unit_col, value_col = _rank_units_for_chart(density, count_col, 15) if count_col else (pd.DataFrame(), None, None)
            if not rank_df.empty:
                fig = px.bar(rank_df, y=unit_col, x=value_col, orientation="h", title="Top spatial units by crash count")
                fig.update_layout(
                    height=_chart_height(),
                    margin=dict(l=20, r=20, t=45, b=35),
                    yaxis={"categoryorder": "total ascending", "title": "Spatial unit ID"},
                    xaxis_title="Crash count",
                )
                st.plotly_chart(_polish_figure(fig), width="stretch")
            else:
                st.info("Crash count field was not found in the crash-density results.")
        else:
            st.info("Run crash-density analysis to show crash-count ranking.")

    if hin is not None:
        st.markdown("<div class='dashboard-section-title'>HIN priority ranking <span>available after Sliding Window / HIN analysis</span></div>", unsafe_allow_html=True)
        metric = _default_metric(_numeric_cols(hin))
        rank_df, unit_col, value_col = _rank_units_for_chart(hin, metric, 15) if metric else (pd.DataFrame(), None, None)
        if not rank_df.empty:
            fig = px.bar(rank_df, y=unit_col, x=value_col, orientation="h", title=f"Top HIN/risk units by {_nice_metric_label(metric)}")
            fig.update_layout(
                height=_chart_height(),
                margin=dict(l=20, r=20, t=45, b=35),
                yaxis={"categoryorder": "total ascending", "title": "Spatial unit ID"},
                xaxis_title=_nice_metric_label(metric),
            )
            st.plotly_chart(_polish_figure(fig), width="stretch")


def _tokens(text):
    return [t for t in re.findall(r"[a-zA-Z0-9_]+", str(text).lower()) if len(t) >= 2]


def _column_score(query, col):
    q = " ".join(_tokens(query))
    c = str(col).lower()
    c_norm = re.sub(r"[^a-z0-9]+", " ", c)
    score = 0
    if c in q or c_norm.strip() in q:
        score += 12
    for tok in _tokens(query):
        if tok in c_norm.split():
            score += 5
        elif tok in c_norm:
            score += 2
    synonyms = {
        "year": ["year", "date", "time"],
        "type": ["type", "manner", "collision", "crash_type"],
        "severity": ["severity", "kabco", "injury", "fatal", "ksi"],
        "kabco": ["kabco", "severity", "injury"],
        "reason": ["reason", "cause", "factor", "contributing"],
        "unit": ["unit", "intersection", "segment", "corridor", "route", "road"],
        "density": ["density", "crashdensity", "crash_density"],
        "hin": ["hin", "risk", "priority"],
        "count": ["count", "total", "crashes", "crashcount"],
    }
    qtoks = set(_tokens(query))
    for concept, words in synonyms.items():
        if concept in qtoks or any(w in qtoks for w in words):
            if any(w.replace("_", "") in c.replace("_", "") for w in words):
                score += 6
    return score


def _best_column(query, columns, minimum=5):
    scored = sorted([(c, _column_score(query, c)) for c in columns], key=lambda x: x[1], reverse=True)
    if not scored or scored[0][1] < minimum:
        return None, scored[:8]
    if len(scored) > 1 and scored[0][1] == scored[1][1] and scored[0][1] < 12:
        return None, scored[:8]
    return scored[0][0], scored[:8]


def _infer_dataset_from_request(request, tables):
    q = str(request).lower()
    preferences = []
    if any(w in q for w in ["hin", "risk", "priority", "sliding"]):
        preferences += ["HIN risk segments", "HIN corridors", "Sliding windows"]
    if any(w in q for w in ["density", "top", "rank", "intersection", "segment", "corridor", "spatial unit", "spatial"]):
        preferences += ["Crash density results", "Crash count / severity summary"]
    if any(w in q for w in ["type", "year", "severity", "reason", "cause", "factor", "crash"]):
        preferences += ["Assigned crashes", "Uploaded crashes"]
    preferences += list(tables.keys())
    for name in preferences:
        if name in tables:
            return name
    return next(iter(tables.keys()))


def _infer_chart_type(request, group_col=None):
    q = str(request).lower()
    if any(w in q for w in ["table", "list", "records"]):
        return "Table"
    if any(w in q for w in ["pie", "share", "percent", "percentage", "composition"]):
        return "Pie chart"
    if any(w in q for w in ["histogram", "distribution"]):
        return "Histogram"
    if any(w in q for w in ["box", "spread"]):
        return "Box plot"
    if any(w in q for w in ["top", "rank", "highest", "worst", "most", "risky"]):
        return "Horizontal rank bar"
    return "Bar chart"


def _infer_aggregation(request):
    q = str(request).lower()
    if any(w in q for w in ["average", "avg", "mean"]):
        return "Average"
    if "median" in q:
        return "Median"
    if any(w in q for w in ["sum", "total"]):
        return "Sum"
    if any(w in q for w in ["minimum", "min", "lowest"]):
        return "Minimum"
    if any(w in q for w in ["maximum", "max", "highest"]):
        return "Maximum"
    return "Count"


def _infer_top_n(request, default=15):
    m = re.search(r"top\s+(\d+)", str(request).lower())
    if m:
        return max(1, min(100, int(m.group(1))))
    return default



def _infer_color_col(request, df, group_col=None):
    """Find a second grouping/color column, especially for commands like
    'count crashes in each intersection colored by crash type'.
    """
    q = str(request).lower()
    if not any(w in q for w in ["color", "colored", "stack", "stacked", "by crash type", "each intersection"]):
        return None
    if any(w in q for w in ["crash type", "type", "collision", "manner"]):
        col = _crash_type_col(df)
        if col and col != group_col:
            return col
    # Look after words such as colored by / stacked by.
    m = re.search(r"(?:colored by|color by|stacked by|split by)\s+([a-zA-Z0-9_ ]+)", q)
    if m:
        col, _ = _best_column(m.group(1), _groupable_cols(df), minimum=4)
        if col and col != group_col:
            return col
    return None

def _infer_map_layers(request, maps):
    q = str(request).lower()
    selected = []
    for name in maps:
        lname = name.lower()
        if ("density" in q and "density" in lname) or ("hin" in q and "hin" in lname) or ("risk" in q and "hin" in lname) or ("corridor" in q and "corridor" in lname) or ("map" in q and not selected):
            selected.append(name)
    if "map" in q and not selected:
        selected = list(maps.keys())[:1]
    return selected[:2]


def _figure_to_png_bytes(fig):
    try:
        return pio.to_image(fig, format="png", width=1200, height=720, scale=2)
    except Exception:
        return None


def _render_chart_download_buttons(st, fig, data, base_name, key_prefix):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "Download data CSV",
            data=data.to_csv(index=False).encode("utf-8"),
            file_name=f"{_safe_name(base_name)}.csv",
            mime="text/csv",
            key=f"{key_prefix}_csv",
        )
    if fig is not None:
        with c2:
            st.download_button(
                "Download chart HTML",
                data=pio.to_html(fig, include_plotlyjs="cdn", full_html=True).encode("utf-8"),
                file_name=f"{_safe_name(base_name)}.html",
                mime="text/html",
                key=f"{key_prefix}_html",
            )
        with c3:
            png = _figure_to_png_bytes(fig)
            if png:
                st.download_button(
                    "Download chart PNG",
                    data=png,
                    file_name=f"{_safe_name(base_name)}.png",
                    mime="image/png",
                    key=f"{key_prefix}_png",
                )
            else:
                st.caption("PNG export needs kaleido.")


def _generate_assistant_chart(request, tables):
    dataset = _infer_dataset_from_request(request, tables)
    df = tables[dataset].copy()
    num_cols = _numeric_cols(df)
    group_cols = _groupable_cols(df)
    aggregation = _infer_aggregation(request)
    top_n = _infer_top_n(request)
    q = str(request).lower()

    # Better handling for spatial-unit crash summaries.
    group_col, group_candidates = _best_column(request, group_cols, minimum=5)
    if any(w in q for w in ["intersection", "segment", "corridor", "spatial unit", "spatial"]):
        possible_unit = _unit_col(df)
        if possible_unit:
            group_col = possible_unit

    value_col = None
    value_candidates = []
    if aggregation != "Count" or any(w in q for w in ["density", "hin", "risk", "score", "index", "epdo", "ksi"]):
        value_col, value_candidates = _best_column(request, num_cols, minimum=5)
        if value_col is None:
            value_col = _default_metric(num_cols)

    # Sensible defaults for common crash requests.
    if group_col is None:
        if "year" in q:
            group_col = _find_col(df, ["year"])
        elif "type" in q:
            group_col = _crash_type_col(df)
        elif any(w in q for w in ["severity", "kabco", "injury"]):
            group_col = _kabco_col(df) or _find_col(df, ["severity"])
        elif any(w in q for w in ["unit", "intersection", "segment", "corridor", "rank", "top"]):
            group_col = _unit_col(df)

    color_col = _infer_color_col(request, df, group_col=group_col)
    chart_type = _infer_chart_type(request, group_col)
    if color_col and group_col:
        chart_type = "Stacked bar chart"
    elif "type" in q and any(w in q for w in ["share", "pie", "percent", "percentage"]):
        chart_type = "Pie chart"
    elif any(w in q for w in ["top", "rank", "highest", "worst", "most", "risky"]):
        chart_type = "Horizontal rank bar"

    value_col_for_render = None if aggregation == "Count" else value_col
    needs_clarification = group_col is None and chart_type not in ["Histogram", "Box plot", "Table"]
    if chart_type in ["Histogram", "Box plot"] and value_col is None:
        needs_clarification = True

    return {
        "dataset": dataset,
        "df": df,
        "group_col": group_col,
        "color_col": color_col,
        "value_col": value_col_for_render,
        "aggregation": aggregation,
        "chart_type": chart_type,
        "top_n": top_n,
        "needs_clarification": needs_clarification,
        "group_candidates": group_candidates,
        "value_candidates": value_candidates,
    }


def _render_smart_dashboard_assistant(st, tables):
    maps = _available_maps(st)
    st.markdown("<div class='dashboard-section-title'>Dashboard assistant <span>ask for charts, tables, maps, dashboards, or reports in plain language</span></div>", unsafe_allow_html=True)
    st.caption("Type what you want. The assistant searches all uploaded and generated datasets. If a requested column is unclear, it asks for the exact dataset column name.")

    request = st.chat_input("Example: Show crash type share as a pie chart and add crash density map to the dashboard")
    if request:
        history = st.session_state.get("dashboard_assistant_messages", [])
        history.append({"role": "user", "content": request})
        st.session_state["dashboard_assistant_messages"] = history[-12:]
        st.session_state["dashboard_assistant_request"] = request

    for msg in st.session_state.get("dashboard_assistant_messages", []):
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    current_request = st.session_state.get("dashboard_assistant_request", "")
    if not current_request:
        st.info("Try: 'create a pie chart of crash type', 'top 10 intersections by crash density', or 'make a dashboard with crash years, crash type, top risky units, and crash density map'.")
        return

    plan = _generate_assistant_chart(current_request, tables)
    selected_maps = _infer_map_layers(current_request, maps)
    q = current_request.lower()
    dashboard_request = any(w in q for w in ["dashboard", "report", "include", "add", "put"])

    if plan["needs_clarification"]:
        st.warning("I found the dataset, but I need one exact column name before creating the chart.")
        st.write(f"Dataset selected: **{plan['dataset']}**")
        df = plan["df"]
        group_options = _groupable_cols(df)
        num_options = _numeric_cols(df)
        if plan["group_col"] is None and plan["chart_type"] not in ["Histogram", "Box plot", "Table"]:
            candidates = [c for c, score in plan["group_candidates"] if score > 0]
            default_idx = 0
            options = candidates + [c for c in group_options if c not in candidates]
            if not options:
                options = group_options
            chosen_group = st.selectbox("Which exact column should be the category/group field?", options, key="smart_assistant_group_confirm")
            plan["group_col"] = chosen_group
        if plan["chart_type"] in ["Histogram", "Box plot"] and plan["value_col"] is None:
            chosen_value = st.selectbox("Which exact numeric column should be used as the value field?", num_options, key="smart_assistant_value_confirm")
            plan["value_col"] = chosen_value
        if not st.button("Create chart with this column", key="smart_assistant_create_after_confirm"):
            return

    st.markdown("**Assistant plan**")
    st.write(
        f"Dataset: **{plan['dataset']}** · Chart: **{plan['chart_type']}** · "
        f"Group: **{plan['group_col'] or 'None'}** · Calculation: **{plan['aggregation']}**"
        + (f" · Color: **{plan.get('color_col')}**" if plan.get('color_col') else "")
        + (f" · Value: **{plan['value_col']}**" if plan['value_col'] else "")
    )

    chart_data, fig = _render_chart(
        st=st,
        df=plan["df"],
        chart_type=plan["chart_type"],
        value_field=plan["value_col"],
        aggregation=plan["aggregation"],
        group_col=plan["group_col"],
        top_n=plan["top_n"],
        color_col=plan.get("color_col"),
    )
    title = "Assistant table" if fig is None else (fig.layout.title.text or "Assistant chart")
    _render_chart_download_buttons(st, fig, chart_data, title, "smart_assistant_current")

    c1, c2, c3 = st.columns(3)
    with c1:
        if fig is not None and st.button("Add chart to dashboard", key="smart_assistant_add_chart"):
            saved = st.session_state.get("dashboard_custom_figures", [])
            saved.append((str(title), fig, chart_data.copy()))
            st.session_state["dashboard_custom_figures"] = saved[-12:]
            st.success("Chart added to Dashboard Builder.")
    with c2:
        if selected_maps:
            st.write("Map layers found from your request:")
            st.write(", ".join(selected_maps))
            if st.button("Add map layers to dashboard", key="smart_assistant_add_maps"):
                st.session_state["dash_builder_map_layers"] = selected_maps
                st.success("Map layers added to Dashboard Builder.")
    with c3:
        if dashboard_request:
            if st.button("Build dashboard from this request", key="smart_assistant_build_dashboard"):
                if fig is not None:
                    saved = st.session_state.get("dashboard_custom_figures", [])
                    saved.append((str(title), fig, chart_data.copy()))
                    st.session_state["dashboard_custom_figures"] = saved[-12:]
                if selected_maps:
                    st.session_state["dash_builder_map_layers"] = selected_maps
                st.success("Dashboard Builder updated. Open the Dashboard builder tab to review/export.")

    if selected_maps:
        st.markdown("**Preview requested map layer**")
        map_name = selected_maps[0]
        _render_dashboard_map(st, map_name, maps[map_name], key=f"smart_assistant_map_{_safe_name(map_name)}", height=430, overlay_layers={name: gdf for name, gdf in _workflow_overlay_sources(st).items() if name in ["Roads", "Signals"]})

def _render_chart(st, df, chart_type, value_field, aggregation, group_col, top_n, color_col=None):
    if chart_type == "Table":
        ranked = _rank_table(df, value_field)
        default_cols = list(ranked.columns)[: min(14, len(ranked.columns))]
        show_cols = st.multiselect("Columns to show", list(ranked.columns), default=default_cols, key="dash_columns_to_show")
        st.dataframe(_safe_dataframe_for_display(ranked[show_cols] if show_cols else ranked), width="stretch", hide_index=True)
        return ranked, None

    if chart_type == "Summary cards":
        numeric = _numeric_cols(df)
        selected = st.multiselect("Value fields", numeric, default=[c for c in [value_field] if c in numeric] or numeric[:4], key="dash_summary_metric_fields")
        if not selected:
            st.info("Choose at least one numeric field.")
            return df, None
        card_cols = st.columns(min(4, len(selected)))
        for i, col in enumerate(selected):
            values = pd.to_numeric(df[col], errors="coerce")
            with card_cols[i % len(card_cols)]:
                st.metric(f"Average {col}", f"{values.mean():,.2f}")
                st.caption(f"sum {values.sum():,.2f} | median {values.median():,.2f}")
        return df, None

    if chart_type == "Stacked bar chart":
        if not group_col or not color_col:
            st.warning("Choose both a spatial-unit/category field and a color/group field.")
            return df, None
        work = df.copy()
        work[group_col] = work[group_col].fillna("Unknown").astype(str)
        work[color_col] = work[color_col].fillna("Unknown").astype(str)
        # Keep the top spatial units by total count, then split those bars by crash type.
        top_units = work.groupby(group_col).size().sort_values(ascending=False).head(top_n).index.tolist()
        work = work[work[group_col].isin(top_units)]
        chart_df = work.groupby([group_col, color_col], dropna=False).size().reset_index(name="Count")
        order = chart_df.groupby(group_col)["Count"].sum().sort_values(ascending=True).index.tolist()
        chart_df[group_col] = pd.Categorical(chart_df[group_col], categories=order, ordered=True)
        fig = px.bar(
            chart_df.sort_values(group_col),
            y=group_col,
            x="Count",
            color=color_col,
            orientation="h",
            title=f"Crashes in each {group_col} by {color_col}",
        )
        fig.update_layout(height=360, margin=dict(l=20, r=20, t=45, b=35), barmode="stack")
        st.plotly_chart(_polish_figure(fig), width="stretch")
        return chart_df, fig

    if chart_type in ["Bar chart", "Horizontal rank bar", "Pie chart"]:
        if not group_col:
            st.warning("Choose a group/category field.")
            return df, None
        chart_df = _aggregate(df, group_col, value_field, aggregation, top_n)
        if chart_df.empty:
            st.warning("No data to display.")
            return df, None
        value_col = [c for c in chart_df.columns if c not in ["Rank", group_col]][0]
        if chart_type == "Pie chart":
            fig = px.pie(chart_df, names=group_col, values=value_col, hole=0.35, title=f"{group_col} by {aggregation.lower()}")
        elif chart_type == "Horizontal rank bar":
            fig = px.bar(chart_df, y=group_col, x=value_col, orientation="h", title=f"Top {top_n} {group_col}")
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
        else:
            fig = px.bar(chart_df, x=group_col, y=value_col, title=f"Top {top_n} {group_col}")
        fig.update_layout(height=360, margin=dict(l=20, r=20, t=45, b=40))
        st.plotly_chart(_polish_figure(fig), width="stretch")
        return chart_df, fig

    if chart_type == "Histogram":
        if not value_field:
            st.warning("Choose a numeric value field for the histogram.")
            return df, None
        fig = px.histogram(df, x=value_field, nbins=25, title=f"Distribution of {value_field}")
        fig.update_layout(height=360, margin=dict(l=20, r=20, t=45, b=40))
        st.plotly_chart(_polish_figure(fig), width="stretch")
        return df[[value_field]].copy(), fig

    if chart_type == "Box plot":
        if not value_field:
            st.warning("Choose a numeric value field for the box plot.")
            return df, None
        if group_col:
            fig = px.box(df, x=group_col, y=value_field, title=f"{value_field} by {group_col}")
        else:
            fig = px.box(df, y=value_field, title=f"{value_field} distribution")
        fig.update_layout(height=360, margin=dict(l=20, r=20, t=45, b=40))
        st.plotly_chart(_polish_figure(fig), width="stretch")
        return df, fig

    return df, None


def _metric_for_map(gdf, map_name):
    cols = list(gdf.columns)
    if "HIN" in map_name:
        for c in ["HIN_Priority_Index", "RiskScore", "CrashDensity", "CrashCount"]:
            if c in cols:
                return c
    if "density" in map_name.lower():
        for c in ["CrashDensity", "CrashDensity_per_mile", "CrashCount", "Crash_Count"]:
            if c in cols:
                return c
    for c in ["CrashDensity", "HIN_Priority_Index", "CrashCount", "Crash_Count"]:
        if c in cols:
            return c
    nums = _numeric_cols(_drop_geometry(gdf))
    return nums[0] if nums else None


def _style_feature(value, min_value, max_value, highlight=False):
    """Dashboard/result map colors: same green-yellow-orange-red ramp as workflow maps."""
    if highlight:
        return {"color": "#111827", "weight": 5, "fillColor": "#f97316", "fillOpacity": 0.80}
    if value is None or pd.isna(value) or max_value == min_value:
        color = "#16a34a"
    else:
        ratio = max(0.0, min(1.0, (float(value) - float(min_value)) / (float(max_value) - float(min_value))))
        if ratio < 0.25:
            color = "#16a34a"      # low = green
        elif ratio < 0.50:
            color = "#facc15"      # moderate = yellow
        elif ratio < 0.75:
            color = "#f97316"      # high = orange
        else:
            color = "#dc2626"      # highest = red
    return {"color": color, "weight": 3, "fillColor": color, "fillOpacity": 0.62}




def _workflow_overlay_sources(st):
    """Return optional workflow layers that can be shown on dashboard maps."""
    sources = {}
    for label, state_key in [
        ("Roads", "selected_roads"),
        ("Road class layer", "roads_class_display"),
        ("Signals", "signals_clean"),
        ("Crash points", "crashes"),
        ("Corridors", "final_corridors"),
        ("Generated corridors", "corridors"),
        ("Study boundary", "selected_boundary"),
    ]:
        data = st.session_state.get(state_key)
        if data is not None and not getattr(data, "empty", True):
            sources[label] = data
    # Avoid duplicate corridor choices when final_corridors and corridors are the same purpose.
    if "Corridors" in sources and "Generated corridors" in sources:
        pass
    return sources


def _overlay_style(label):
    lname = label.lower()
    if "road" in lname:
        return {"color": "#6b7280", "weight": 2, "opacity": 0.65, "fillOpacity": 0.0}
    if "signal" in lname:
        return {"color": "#16a34a", "weight": 2, "opacity": 0.9, "fillColor": "#22c55e", "fillOpacity": 0.9, "radius": 5}
    if "crash" in lname:
        return {"color": "#111827", "weight": 1, "opacity": 0.85, "fillColor": "#ef4444", "fillOpacity": 0.7, "radius": 3}
    if "boundary" in lname:
        return {"color": "#111827", "weight": 2, "opacity": 0.85, "fillOpacity": 0.02}
    if "corridor" in lname:
        return {"color": "#7c3aed", "weight": 3, "opacity": 0.85, "fillOpacity": 0.05}
    return {"color": "#374151", "weight": 2, "opacity": 0.7, "fillOpacity": 0.1}


def _add_overlay_layer(fmap, gdf, label, show=False):
    if gdf is None or getattr(gdf, "empty", True) or folium is None:
        return
    try:
        layer = gdf.copy()
        if layer.crs is None:
            layer = layer.set_crs(epsg=4326)
        layer = layer.to_crs(epsg=4326)
        style = _overlay_style(label)
        group = folium.FeatureGroup(name=label, show=show)
        # Points are rendered as circle markers for readability.
        if all(getattr(geom, "geom_type", "") == "Point" for geom in layer.geometry.dropna().head(50)):
            for _, row in layer.iterrows():
                geom = row.geometry
                if geom is None or geom.is_empty:
                    continue
                popup_cols = [c for c in ["CrashID", "SignalID", "CorridorID", "Route", "FULLNAME"] if c in layer.columns]
                popup = "<br>".join([f"{c}: {row.get(c)}" for c in popup_cols]) if popup_cols else label
                folium.CircleMarker(
                    location=[geom.y, geom.x],
                    radius=style.get("radius", 4),
                    color=style.get("color", "#111827"),
                    weight=style.get("weight", 1),
                    fill=True,
                    fill_color=style.get("fillColor", style.get("color", "#111827")),
                    fill_opacity=style.get("fillOpacity", 0.8),
                    popup=popup,
                ).add_to(group)
        else:
            gj = _safe_geojson_string(layer)
            if gj:
                folium.GeoJson(
                    gj,
                    name=label,
                    style_function=lambda feature, stl=style: stl,
                ).add_to(group)
        group.add_to(fmap)
    except Exception:
        return

def _fit_bounds_for_layer(work):
    """Return finite bounds and padded bounds for Leaflet/Matplotlib."""
    try:
        clean = work[work.geometry.notna() & (~work.geometry.is_empty)].copy()
        if clean.empty:
            clean = work
        minx, miny, maxx, maxy = [float(v) for v in clean.total_bounds]
        if not all(pd.notna(v) for v in [minx, miny, maxx, maxy]):
            return None
        if minx == maxx:
            minx -= 0.002
            maxx += 0.002
        if miny == maxy:
            miny -= 0.002
            maxy += 0.002
        return minx, miny, maxx, maxy
    except Exception:
        return None


def _render_dashboard_map(st, map_name, gdf, key, highlight_value=None, height=460, overlay_layers=None):
    if folium is None or st_folium is None:
        st.info("Install folium and streamlit-folium to show dashboard maps.")
        return
    if gdf is None or getattr(gdf, "empty", True):
        st.info("No map data is available for this layer.")
        return
    work = _repair_gdf_crs(gdf, st)
    work = work.to_crs(epsg=4326)
    bounds = _fit_bounds_for_layer(work)
    if bounds is None:
        st.info("Map bounds could not be calculated for this layer.")
        return
    minx, miny, maxx, maxy = bounds
    center = [(miny + maxy) / 2, (minx + maxx) / 2]
    fmap = folium.Map(location=center, zoom_start=13, tiles="cartodbpositron")
    metric = _metric_for_map(work, map_name)
    values = pd.to_numeric(work[metric], errors="coerce") if metric else pd.Series([], dtype=float)
    min_value = values.min() if not values.empty else 0
    max_value = values.max() if not values.empty else 1
    unit_col = _unit_col(_drop_geometry(work))
    tooltip_cols = [c for c in [unit_col, metric, "CrashCount", "Crash_Count", "Rank"] if c and c in work.columns]

    def style_fn(feature):
        props = feature.get("properties", {})
        val = props.get(metric) if metric else None
        highlight = False
        if highlight_value is not None and unit_col and props.get(unit_col) is not None:
            highlight = str(props.get(unit_col)) == str(highlight_value)
        return _style_feature(val, min_value, max_value, highlight=highlight)

    tooltip = GeoJsonTooltip(fields=tooltip_cols, aliases=tooltip_cols) if GeoJsonTooltip and tooltip_cols else None
    gj = _safe_geojson_string(work)
    if not gj:
        return "<p>Map geometry could not be converted to displayable GeoJSON.</p>"
    folium.GeoJson(gj, name=map_name, style_function=style_fn, tooltip=tooltip, show=True).add_to(fmap)
    if metric:
        _add_map_legend(fmap, _nice_metric_label(metric), min_value, max_value)
    for overlay_name, overlay_gdf in (overlay_layers or {}).items():
        _add_overlay_layer(fmap, overlay_gdf, overlay_name, show=False)
    folium.LayerControl(collapsed=False).add_to(fmap)
    try:
        fmap.fit_bounds([[miny, minx], [maxy, maxx]], padding=(24, 24))
    except Exception:
        pass
    map_key = f"{key}_{round(minx,5)}_{round(miny,5)}_{round(maxx,5)}_{round(maxy,5)}"
    st_folium(fmap, height=height, width="100%", key=map_key, returned_objects=[])


def _build_default_figures(tables):
    figures = []
    crashes = tables.get("Assigned crashes", tables.get("Uploaded crashes"))
    density = tables.get("Crash density results")
    hin = tables.get("HIN risk segments", tables.get("HIN corridors"))
    if crashes is not None:
        year_col = _find_col(crashes, ["year"])
        if year_col:
            year_df = _aggregate(crashes, year_col, None, "Count", 20)
            fig = px.bar(year_df.sort_values(year_col), x=year_col, y="Count", title="Crashes by year")
            figures.append(("Crashes by year", fig, year_df))
        type_col = _find_col(crashes, ["crash", "type"]) or _find_col(crashes, ["type"]) or _find_col(crashes, ["kabco"]) or _find_col(crashes, ["severity"])
        if type_col:
            type_df = _aggregate(crashes, type_col, None, "Count", 12)
            pie = px.pie(type_df, names=type_col, values="Count", hole=0.38, title=f"Crash type share by {type_col}")
            figures.append((f"Crash type share by {type_col}", pie, type_df))
        road_title, road_df, road_class_col, road_value_col = _road_class_summary_table(crashes=crashes, density=density)
        if road_title and not road_df.empty:
            fig = px.bar(road_df, y=road_class_col, x=road_value_col, orientation="h", title=road_title)
            fig.update_layout(yaxis_title="Road class", xaxis_title=road_value_col)
            figures.append((road_title, fig, road_df))
        kabco_col = _kabco_col(crashes)
        if kabco_col and kabco_col != type_col:
            kabco_df = _aggregate(crashes, kabco_col, None, "Count", 10)
            kabco_df = _order_kabco(kabco_df, kabco_col)
            fig = px.bar(kabco_df, x=kabco_col, y="Count", title=f"KABCO / severity distribution by {kabco_col}")
            figures.append((f"KABCO / severity distribution by {kabco_col}", fig, kabco_df))
    if density is not None:
        metric = "CrashDensity" if "CrashDensity" in density.columns else _default_metric(_numeric_cols(density))
        rank_df, unit_col, value_col = _rank_units_for_chart(density, metric, 15) if metric else (pd.DataFrame(), None, None)
        if not rank_df.empty:
            fig = px.bar(rank_df, y=unit_col, x=value_col, orientation="h", title="Top spatial units by crash density")
            fig.update_layout(yaxis_title="Spatial unit ID", xaxis_title="Crash density")
            figures.append(("Top spatial units by crash density", fig, rank_df))
    if hin is not None:
        metric = _default_metric(_numeric_cols(hin))
        rank_df, unit_col, value_col = _rank_units_for_chart(hin, metric, 15) if metric else (pd.DataFrame(), None, None)
        if not rank_df.empty:
            fig = px.bar(rank_df, y=unit_col, x=value_col, orientation="h", title=f"Top HIN/risk units by {_nice_metric_label(metric)}")
            fig.update_layout(yaxis_title="Spatial unit ID", xaxis_title=_nice_metric_label(metric))
            figures.append((f"Top HIN/risk units by {_nice_metric_label(metric)}", fig, rank_df))
    return figures



def _normal_col(df, candidates):
    if df is None:
        return None
    lower_map = {str(c).lower().replace("_", "").replace(" ", ""): c for c in df.columns}
    for cand in candidates:
        key = cand.lower().replace("_", "").replace(" ", "")
        if key in lower_map:
            return lower_map[key]
    for c in df.columns:
        cl = str(c).lower()
        if any(cand.lower() in cl for cand in candidates):
            return c
    return None


def _top_density_export_table(density, top_n=20):
    """Decision-ready top crash-density table with only useful columns."""
    if density is None or getattr(density, "empty", True):
        return pd.DataFrame()
    df = _drop_geometry(density).copy()
    unit_col = _unit_col(df) or _normal_col(df, ["UnitID", "IntersectionID", "CorridorID", "SegmentID", "Route"])
    unit_type_col = _normal_col(df, ["UnitType", "IntersectionType", "CorridorType", "SegmentType"])
    city_col = _normal_col(df, ["City", "city_name"])
    length_col = _normal_col(df, ["Length_Miles", "Length_Mi", "length_mi", "Miles"])
    count_col = _crash_count_col(df)
    density_col = _normal_col(df, ["CrashDensity", "Crash_Density", "crash_density"])
    if density_col is None:
        density_col = _default_metric(_numeric_cols(df))
    if density_col:
        df[density_col] = pd.to_numeric(df[density_col], errors="coerce").fillna(0)
        df = df.sort_values(density_col, ascending=False)
    out = pd.DataFrame()
    out["Rank"] = range(1, min(top_n, len(df)) + 1)
    use = df.head(top_n).reset_index(drop=True)
    out["Spatial unit id"] = use[unit_col].astype(str) if unit_col else use.index.astype(str)
    out["Unit type"] = use[unit_type_col].astype(str) if unit_type_col else ""
    out["City"] = use[city_col].astype(str) if city_col else ""
    out["Length_mi"] = pd.to_numeric(use[length_col], errors="coerce").round(3) if length_col else ""

    # Context columns requested for decision tables. Intersections show the two
    # crossing roads; corridors/segments show route name when available.
    road1_col = _normal_col(use, ["RoadName1", "Road1", "Route1", "Street1", "FromRoad"])
    road2_col = _normal_col(use, ["RoadName2", "Road2", "Route2", "Street2", "ToRoad"])
    route_col = _normal_col(use, ["Route", "FULLNAME", "RoadName", "RouteName", "CorridorRoute", "RouteName_Calc"])
    unit_type_text = str(use[unit_type_col].iloc[0]).lower() if unit_type_col and len(use) else ""
    if road1_col and road2_col:
        out["Road 1"] = use[road1_col].astype(str)
        out["Road 2"] = use[road2_col].astype(str)
    elif route_col:
        out["Route name"] = use[route_col].astype(str)

    out["Crash count"] = pd.to_numeric(use[count_col], errors="coerce").fillna(0).astype(int) if count_col else ""
    out["Crash density"] = pd.to_numeric(use[density_col], errors="coerce").round(3) if density_col else ""
    return out


def _top_hin_export_table(hin, top_n=20):
    if hin is None or getattr(hin, "empty", True):
        return pd.DataFrame()
    df = _drop_geometry(hin).copy()
    metric = _default_metric(_numeric_cols(df))
    unit_col = _unit_col(df) or _normal_col(df, ["UnitID", "RiskSegmentID", "WindowID", "SegmentID", "CorridorID", "Route"])
    if unit_col is not None and any(bad in str(unit_col).lower() for bad in ["length", "mile", "density", "count", "score", "index"]):
        unit_col = None
    if metric:
        df[metric] = pd.to_numeric(df[metric], errors="coerce").fillna(0)
        df = df.sort_values(metric, ascending=False)
    use = df.head(top_n).reset_index(drop=True)
    out = pd.DataFrame({"Rank": range(1, len(use) + 1)})
    out["Spatial unit id"] = use[unit_col].astype(str) if unit_col else [f"UNIT_{i + 1}" for i in range(len(use))]
    if "UnitType" in use.columns:
        out["Unit type"] = use["UnitType"].astype(str)
    route_col = _normal_col(use, ["Route", "FULLNAME", "RoadName", "RouteName", "RouteName_Calc"])
    if route_col:
        out["Route name"] = use[route_col].astype(str)
    if "Length_Miles" in use.columns:
        out["Length_mi"] = pd.to_numeric(use["Length_Miles"], errors="coerce").round(3)
    if metric:
        out[metric] = pd.to_numeric(use[metric], errors="coerce").round(3)
    return out


def _severity_summary_export(summary, top_n=20):
    if summary is None or getattr(summary, "empty", True):
        return pd.DataFrame()
    df = _drop_geometry(summary).copy()
    metric = _crash_count_col(df) or _normal_col(df, ["Total", "CrashCount", "Crash_Count", "CrashDensity"])
    if metric and metric in df.columns:
        df[metric] = pd.to_numeric(df[metric], errors="coerce").fillna(0)
        df = df.sort_values(metric, ascending=False)
    df = df.head(top_n).copy().reset_index(drop=True)
    if "Rank" not in df.columns:
        df.insert(0, "Rank", range(1, len(df) + 1))
    keep = [c for c in ["Rank", "UnitID", "UnitType", "City", "CrashCount", "CrashDensity", "K", "A", "B", "C", "O", "Total"] if c in df.columns]
    return df[keep] if keep else df.iloc[:, :min(8, len(df.columns))]


def _export_tables_only(tables, top_n=20):
    """Return only report-ready summary tables.

    Excludes raw uploaded/assigned rows and the KABCO distribution table because
    KABCO is already shown as a chart. Ranking is only used for spatial-unit
    priority tables.
    """
    out = {}
    crashes = tables.get("Assigned crashes", tables.get("Uploaded crashes"))
    density = tables.get("Crash density results")
    hin = tables.get("HIN risk segments", tables.get("HIN corridors"))
    summary = tables.get("Crash count / severity summary")

    if crashes is not None:
        type_col = _crash_type_col(crashes)
        year_col = _find_col(crashes, ["year"])
        if type_col:
            out["Crash type summary"] = _aggregate(crashes, type_col, None, "Count", top_n)
        if year_col:
            out["Crash year summary"] = _aggregate(crashes, year_col, None, "Count", top_n)

    if density is not None:
        top_density = _top_density_export_table(density, top_n=top_n)
        if not top_density.empty:
            out["Top crash-density spatial units"] = top_density

    if summary is not None:
        sev = _severity_summary_export(summary, top_n=top_n)
        if not sev.empty:
            out["Severity summary by spatial unit"] = sev

    if hin is not None:
        top_hin = _top_hin_export_table(hin, top_n=top_n)
        if not top_hin.empty:
            out["Top HIN/risk spatial units"] = top_hin

    return {name: _safe_dataframe_for_display(df) for name, df in out.items()}

def _download_excel_bytes(tables):
    buffer = io.BytesIO()
    export_tables = _export_tables_only(tables)
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, df in export_tables.items():
            sheet = _safe_name(name)[:31] or "data"
            _drop_geometry(df).to_excel(writer, sheet_name=sheet, index=False)
    buffer.seek(0)
    return buffer.getvalue()





def _legend_html(title, min_value, max_value):
    try:
        min_label = f"{float(min_value):,.2f}"
        max_label = f"{float(max_value):,.2f}"
    except Exception:
        min_label, max_label = "Low", "High"
    return f"""
    <div style='position: fixed; bottom: 28px; right: 28px; z-index:9999;
         background: white; border: 1px solid #d1d5db; border-radius: 10px;
         padding: 10px 12px; font-size: 12px; box-shadow: 0 6px 18px rgba(0,0,0,.12);'>
      <div style='font-weight:700; margin-bottom:6px;'>{html.escape(str(title))}</div>
      <div><span style='background:#16a34a;display:inline-block;width:14px;height:10px;margin-right:6px;'></span>Low ({min_label})</div>
      <div><span style='background:#facc15;display:inline-block;width:14px;height:10px;margin-right:6px;'></span>Moderate</div>
      <div><span style='background:#f97316;display:inline-block;width:14px;height:10px;margin-right:6px;'></span>High</div>
      <div><span style='background:#dc2626;display:inline-block;width:14px;height:10px;margin-right:6px;'></span>Highest ({max_label})</div>
    </div>
    """


def _add_map_legend(fmap, title, min_value, max_value):
    try:
        from branca.element import Element
        fmap.get_root().html.add_child(Element(_legend_html(title, min_value, max_value)))
    except Exception:
        pass

def _dashboard_map_html(map_name, gdf, height=520, overlay_layers=None):
    if folium is None or gdf is None or getattr(gdf, "empty", True):
        return "<p>No map data available.</p>"
    work = _repair_gdf_crs(gdf, None)
    work = work.to_crs(epsg=4326)
    bounds = _fit_bounds_for_layer(work)
    if bounds is None:
        return "<p>Map bounds could not be calculated.</p>"
    minx, miny, maxx, maxy = bounds
    fmap = folium.Map(location=[(miny + maxy) / 2, (minx + maxx) / 2], zoom_start=13, tiles="cartodbpositron", height=height)
    metric = _metric_for_map(work, map_name)
    values = pd.to_numeric(work[metric], errors="coerce") if metric else pd.Series([], dtype=float)
    min_value = values.min() if not values.empty else 0
    max_value = values.max() if not values.empty else 1
    unit_col = _unit_col(_drop_geometry(work))
    tooltip_cols = [c for c in [unit_col, metric, "CrashCount", "Crash_Count", "Rank"] if c and c in work.columns]
    def style_fn(feature):
        props = feature.get("properties", {})
        return _style_feature(props.get(metric) if metric else None, min_value, max_value, highlight=False)
    tooltip = GeoJsonTooltip(fields=tooltip_cols, aliases=tooltip_cols) if GeoJsonTooltip and tooltip_cols else None
    gj = _safe_geojson_string(work)
    if not gj:
        return "<p>Map geometry could not be converted to displayable GeoJSON.</p>"
    folium.GeoJson(gj, name=map_name, style_function=style_fn, tooltip=tooltip, show=True).add_to(fmap)
    if metric:
        _add_map_legend(fmap, _nice_metric_label(metric), min_value, max_value)
    for overlay_name, overlay_gdf in (overlay_layers or {}).items():
        _add_overlay_layer(fmap, overlay_gdf, overlay_name, show=False)
    folium.LayerControl(collapsed=False).add_to(fmap)
    try:
        fmap.fit_bounds([[miny, minx], [maxy, maxx]], padding=(24, 24))
    except Exception:
        pass
    return fmap.get_root().render()

def _export_dashboard_html(tables, selected_blocks, selected_maps, maps=None, extra_figures=None, overlay_layers=None):
    figures = _build_default_figures(tables) + (extra_figures or [])
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>HIN dashboard report</title>",
        "<style>body{font-family:Arial,sans-serif;margin:32px;color:#1f2937} .card{border:1px solid #e5e7eb;border-radius:14px;padding:16px;margin:14px 0} h1{margin-bottom:4px} h2{margin-top:28px}</style>",
        "</head><body>",
        "<h1>HIN dashboard report</h1>",
        f"<p>Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>",
    ]
    for title, fig, data in figures:
        if title in selected_blocks or not selected_blocks:
            parts.append(f"<div class='card'><h2>{html.escape(title)}</h2>")
            parts.append(pio.to_html(fig, include_plotlyjs="cdn", full_html=False))
            parts.append("</div>")
    if selected_maps:
        parts.append("<div class='card'><h2>Selected map layers</h2>")
        for m in selected_maps:
            parts.append(f"<h3>{html.escape(m)}</h3>")
            if maps and m in maps:
                parts.append(_dashboard_map_html(m, maps[m], overlay_layers=overlay_layers))
            else:
                parts.append(f"<p>{html.escape(m)}</p>")
        parts.append("</div>")
    for name, df in _export_tables_only(tables).items():
        parts.append(f"<div class='card'><h2>{html.escape(name)}</h2>")
        parts.append(_drop_geometry(df).head(25).to_html(index=False, escape=True))
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts).encode("utf-8")



def _static_map_png(gdf, title="Map layer", overlay_layers=None):
    """Create a static map image for Word/PNG exports.

    This uses the same result geometry and optional workflow context layers
    (roads/signals/corridors/boundary) so the report contains an actual map
    image instead of only a text placeholder or an interactive HTML map.
    """
    if gdf is None or getattr(gdf, "empty", True):
        return None
    try:
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        work = _repair_gdf_crs(gdf, None)
        work = work.to_crs(epsg=4326)
        metric = _metric_for_map(work, title)
        fig, ax = plt.subplots(figsize=(9.5, 6.2))

        # Light context layers first.
        for label, layer in (overlay_layers or {}).items():
            if layer is None or getattr(layer, "empty", True):
                continue
            try:
                ov = layer.copy()
                if ov.crs is None:
                    ov = ov.set_crs(epsg=4326)
                ov = ov.to_crs(epsg=4326)
                lname = str(label).lower()
                if "road" in lname:
                    ov.plot(ax=ax, color="#94a3b8", linewidth=0.55, alpha=0.55)
                elif "signal" in lname and all(getattr(g, "geom_type", "") == "Point" for g in ov.geometry.dropna().head(25)):
                    ov.plot(ax=ax, color="#16a34a", markersize=12, alpha=0.85)
                elif "crash" in lname and all(getattr(g, "geom_type", "") == "Point" for g in ov.geometry.dropna().head(25)):
                    ov.plot(ax=ax, color="#ef4444", markersize=5, alpha=0.45)
                elif "boundary" in lname:
                    ov.boundary.plot(ax=ax, color="#111827", linewidth=1.0, alpha=0.7)
                elif "corridor" in lname:
                    ov.plot(ax=ax, color="#7c3aed", linewidth=1.0, alpha=0.30)
            except Exception:
                pass

        work = _safe_geojson_gdf(work)
        geom_types = set(str(g.geom_type) for g in work.geometry.dropna().head(50))
        if metric and metric in work.columns:
            # Use same low-to-high color meaning as the workflow maps: green -> yellow -> orange -> red.
            # Plot the result layer last and with high z-order so it is visible
            # above context roads/signals in the Word report. For tiny
            # intersection/corridor polygons, add representative-point markers
            # colored by the same metric so the crash-density/HIN layer is clear.
            if geom_types and all("Line" in gt for gt in geom_types):
                work.plot(ax=ax, column=metric, legend=True, cmap="RdYlGn_r", linewidth=4.2, alpha=0.96, zorder=10, legend_kwds={"label": _nice_metric_label(metric), "shrink": 0.72})
            elif geom_types and all(gt == "Point" or gt == "MultiPoint" for gt in geom_types):
                work.plot(ax=ax, column=metric, legend=True, cmap="RdYlGn_r", markersize=46, alpha=0.96, zorder=10, legend_kwds={"label": _nice_metric_label(metric), "shrink": 0.72})
            else:
                work.plot(ax=ax, column=metric, legend=True, cmap="RdYlGn_r", linewidth=1.2, edgecolor="#374151", alpha=0.55, zorder=9, legend_kwds={"label": _nice_metric_label(metric), "shrink": 0.72})
                try:
                    pts = work.copy()
                    pts["geometry"] = pts.geometry.representative_point()
                    pts.plot(ax=ax, column=metric, cmap="RdYlGn_r", markersize=36, alpha=0.98, zorder=12)
                except Exception:
                    pass
        else:
            work.plot(ax=ax, color="#60a5fa", linewidth=1.2, edgecolor="#374151", alpha=0.75, zorder=10)
        bounds = _fit_bounds_for_layer(work)
        if bounds is None:
            return None
        minx, miny, maxx, maxy = bounds
        dx = max((maxx - minx) * 0.08, 0.002)
        dy = max((maxy - miny) * 0.08, 0.002)
        ax.set_xlim(minx - dx, maxx + dx)
        ax.set_ylim(miny - dy, maxy + dy)
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_axis_off()
        legend_items = []
        labels = set((overlay_layers or {}).keys())
        if "Roads" in labels or "Road class layer" in labels:
            legend_items.append(Line2D([0], [0], color="#94a3b8", lw=2, label="Roads"))
        if "Signals" in labels:
            legend_items.append(Line2D([0], [0], marker="o", color="w", markerfacecolor="#16a34a", markersize=7, label="Signals"))
        if "Crash points" in labels:
            legend_items.append(Line2D([0], [0], marker="o", color="w", markerfacecolor="#ef4444", markersize=6, label="Crash points"))
        if legend_items:
            ax.legend(handles=legend_items, loc="lower left", frameon=True, fontsize=8)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight")
        plt.close(fig)
        buffer.seek(0)
        return buffer.getvalue()
    except Exception:
        return None

def _export_dashboard_docx(tables, selected_blocks, selected_maps, extra_figures=None, maps=None, overlay_layers=None):
    if Document is None:
        return None
    doc = Document()
    doc.add_heading("HIN dashboard report", level=0)
    doc.add_paragraph(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}.")
    doc.add_paragraph("This report summarizes crash patterns, crash-density rankings, selected maps, and HIN/risk results from the app dashboard.")

    figures = _build_default_figures(tables) + (extra_figures or [])
    for title, fig, data in figures:
        if selected_blocks and title not in selected_blocks:
            continue
        doc.add_heading(title, level=1)
        try:
            img = pio.to_image(_polish_figure(fig), format="png", width=1200, height=680, scale=2)
            img_buf = io.BytesIO(img)
            doc.add_picture(img_buf, width=Inches(6.5))
        except Exception:
            doc.add_paragraph("Chart image could not be generated. Install kaleido to include chart images.")
        doc.add_paragraph("Summary table")
        table_df = _safe_dataframe_for_display(data.head(15).copy())
        if table_df.empty:
            continue
        table = doc.add_table(rows=1, cols=len(table_df.columns))
        table.style = "Table Grid"
        for i, col in enumerate(table_df.columns):
            table.rows[0].cells[i].text = str(col)
        for _, row in table_df.iterrows():
            cells = table.add_row().cells
            for i, col in enumerate(table_df.columns):
                cells[i].text = str(row[col])

    if selected_maps:
        doc.add_heading("Selected map layers", level=1)
        for m in selected_maps:
            doc.add_heading(str(m), level=2)
            if maps and m in maps:
                map_png = _static_map_png(maps[m], str(m), overlay_layers=overlay_layers)
                if map_png:
                    doc.add_picture(io.BytesIO(map_png), width=Inches(6.5))
                else:
                    doc.add_paragraph("Static map image could not be generated.")
            else:
                doc.add_paragraph("Map layer selected in dashboard builder.")

    doc.add_heading("Decision-ready result tables", level=1)
    for name, df in _export_tables_only(tables).items():
        doc.add_heading(name, level=2)
        table_df = _safe_dataframe_for_display(df).head(20).copy()
        if table_df.empty:
            doc.add_paragraph("No rows.")
            continue
        max_cols = min(10, len(table_df.columns))
        table_df = table_df.iloc[:, :max_cols]
        table = doc.add_table(rows=1, cols=len(table_df.columns))
        table.style = "Table Grid"
        for i, col in enumerate(table_df.columns):
            table.rows[0].cells[i].text = str(col)
        for _, row in table_df.iterrows():
            cells = table.add_row().cells
            for i, col in enumerate(table_df.columns):
                cells[i].text = str(row[col])

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

def _export_summary_image(tables, image_format="png", extra_figures=None):
    figures = _build_default_figures(tables) + (extra_figures or [])
    if not figures:
        return None
    try:
        from PIL import Image
        images = []
        for _, fig, _ in figures[:4]:
            img_bytes = pio.to_image(_polish_figure(fig), format="png", width=900, height=520, scale=2)
            images.append(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
        if not images:
            return None
        cols = 2 if len(images) > 1 else 1
        rows = (len(images) + cols - 1) // cols
        w = max(im.width for im in images)
        h = max(im.height for im in images)
        canvas = Image.new("RGB", (cols * w, rows * h), "white")
        for i, im in enumerate(images):
            canvas.paste(im, ((i % cols) * w, (i // cols) * h))
        buffer = io.BytesIO()
        fmt = "JPEG" if image_format.lower() in ["jpg", "jpeg"] else "PNG"
        canvas.save(buffer, format=fmt, quality=92)
        return buffer.getvalue()
    except Exception:
        try:
            return pio.to_image(_polish_figure(figures[0][1]), format=image_format, width=1400, height=800, scale=2)
        except Exception:
            return None


def _render_dashboard_builder(st, tables):
    maps = _available_maps(st)
    custom_figures = st.session_state.get("dashboard_custom_figures", [])
    default_figures = _build_default_figures(tables) + custom_figures
    figure_titles = [title for title, _, _ in default_figures]

    st.markdown("<div class='dashboard-section-title'>Dashboard builder <span>choose charts, tables, and map layers for one review page</span></div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([0.27, 0.27, 0.46], gap="large")
    with c1:
        st.markdown("**Charts and figures**")
        selected_blocks = st.multiselect(
            "Select dashboard charts",
            figure_titles,
            default=figure_titles[: min(4, len(figure_titles))],
            key="dash_builder_chart_blocks",
        )
        include_tables = st.checkbox("Include ranking/data table previews", value=True, key="dash_builder_include_tables")
        if custom_figures and st.button("Clear added custom charts", key="clear_custom_dashboard_charts"):
            st.session_state["dashboard_custom_figures"] = []
            st.rerun()
    with c2:
        st.markdown("**Map layers**")
        selected_maps = st.multiselect(
            "Select dashboard maps",
            list(maps.keys()),
            default=list(maps.keys())[: min(2, len(maps))],
            key="dash_builder_map_layers",
            help="Dashboard maps are read-only. Map editing and filtering stay in the Visualization section.",
        )
        overlay_sources = _workflow_overlay_sources(st)
        selected_overlays = st.multiselect(
            "Optional workflow layers on dashboard maps",
            list(overlay_sources.keys()),
            default=[name for name in ["Roads", "Signals"] if name in overlay_sources],
            key="dash_builder_overlay_layers",
            help="Turn on context layers such as roads, signals, crash points, corridors, or study boundary.",
        )
        # Highlight selector removed: dashboard maps are read-only context layers.
        highlight_layer = None
        highlight_value = None
    with c3:
        st.markdown("**Exports**")
        st.caption("Export the dashboard as a static PNG summary or a Word report with charts, map summaries, and decision-ready tables.")
        d1, d2 = st.columns(2)
        with d1:
            png_bytes = _export_summary_image(tables, "png", extra_figures=custom_figures)
            if png_bytes:
                st.download_button("Download PNG", data=png_bytes, file_name="hin_dashboard_summary.png", mime="image/png", key="dash_export_png")
            else:
                st.caption("PNG needs kaleido")
        with d2:
            docx_bytes = _export_dashboard_docx(tables, selected_blocks, selected_maps, extra_figures=custom_figures, maps=maps, overlay_layers={name: overlay_sources[name] for name in selected_overlays if name in overlay_sources})
            if docx_bytes is not None:
                st.download_button(
                    "Download Word report",
                    data=docx_bytes,
                    file_name="hin_dashboard_report.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key="dash_export_docx",
                )
            else:
                st.info("Install python-docx for Word export.")

    st.markdown("<div class='dashboard-section-title'>Generated dashboard</div>", unsafe_allow_html=True)
    chart_titles = set(selected_blocks)
    for i in range(0, len(default_figures), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            idx = i + j
            if idx >= len(default_figures):
                continue
            title, fig, data = default_figures[idx]
            if title not in chart_titles:
                continue
            with col:
                fig.update_layout(height=330, margin=dict(l=20, r=20, t=45, b=35))
                st.plotly_chart(_polish_figure(fig), width="stretch", key=f"dash_generated_fig_{idx}")

    if selected_maps:
        map_cols = st.columns(min(2, len(selected_maps)))
        for i, map_name in enumerate(selected_maps[:2]):
            with map_cols[i % len(map_cols)]:
                st.markdown(f"**{map_name}**")
                _render_dashboard_map(
                    st,
                    map_name,
                    maps[map_name],
                    key=f"dash_map_{_safe_name(map_name)}_{i}",
                    height=380,
                    overlay_layers={name: overlay_sources[name] for name in selected_overlays if name in overlay_sources},
                )

    if include_tables:
        table_name = st.selectbox("Dashboard table preview", list(tables.keys()), key="dash_builder_table_preview")
        df = tables[table_name].copy()
        metric = _default_metric(_numeric_cols(df))
        st.dataframe(_safe_dataframe_for_display(_rank_table(df, metric).head(50)), width="stretch", hide_index=True)


def render_dashboard_page(st):
    _style(st)

    st.markdown(
        """
        <div class='dashboard-hero'>
          <h1>Results dashboard</h1>
          <p>Build a decision-ready dashboard with crash trends, crash type summaries, spatial-unit rankings, crash-density maps, and HIN priority maps. Dashboard maps are read-only; analysis results remain unchanged.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    top_left, top_right = st.columns([0.78, 0.22])
    with top_right:
        if st.button("Back to workflow", key="dashboard_back_to_workflow", width="stretch"):
            st.session_state["dashboard_mode"] = False
            st.rerun()

    tables = _available_tables(st)
    if not tables:
        st.info("Run the workflow first. Dashboard options will appear after data or results are available.")
        return

    # Compact production dashboard: remove row/column status cards so charts have more room.

    tab_insights, tab_builder, tab_tables, tab_assistant = st.tabs([
        "Crash insights",
        "Dashboard builder",
        "Data tables",
        "Dashboard assistant",
    ])

    st.markdown("<div class='dashboard-scroll-note'>Scroll down to view all charts, maps, and tables. Use the Dashboard builder tab to select charts/maps for export.</div>", unsafe_allow_html=True)

    with tab_insights:
        _render_pattern_charts(st, tables)

    with tab_builder:
        _render_dashboard_builder(st, tables)

    # Chart Builder was removed from the dashboard navigation.
    # Use Crash insights for default figures, Dashboard assistant for plain-language
    # chart creation, and Dashboard builder to select final charts/maps.

    with tab_tables:
        table_name = st.selectbox("Table", list(tables.keys()), key="dash_full_table_dataset")
        df = tables[table_name].copy()
        search_text = st.text_input("Search table text", key="dash_table_search")
        if search_text:
            mask = df.astype(str).apply(lambda col: col.str.contains(search_text, case=False, na=False)).any(axis=1)
            df = df[mask]
        metric = _default_metric(_numeric_cols(df))
        ranked = _rank_table(df, metric)
        st.dataframe(_safe_dataframe_for_display(ranked), width="stretch", hide_index=True)

        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Download this table CSV",
                data=_safe_dataframe_for_display(ranked).to_csv(index=False).encode("utf-8"),
                file_name=f"dashboard_{_safe_name(table_name)}.csv",
                mime="text/csv",
                key="dashboard_download_table_csv",
            )
        with d2:
            st.download_button(
                "Download all dashboard tables Excel",
                data=_download_excel_bytes(tables),
                file_name="hin_dashboard_tables.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dashboard_download_all_excel",
            )

    with tab_assistant:
        _render_smart_dashboard_assistant(st, tables)
