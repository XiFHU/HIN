"""Folium map utilities for the HIN Streamlit app."""

import io
import zipfile

import folium
import folium.plugins
import pandas as pd
import streamlit as st
import geopandas as gpd

from .layer_manager import is_layer_visible
from .map_symbology import add_categorical_legend, categorical_color_lookup, crash_marker_style

def add_map_elements(fmap):

    folium.plugins.MeasureControl(
        position="bottomleft",
        primary_length_unit="miles",
        secondary_length_unit="feet"
    ).add_to(fmap)

    # Compact north arrow. No background box, and placed below the Leaflet
    # layer control so it does not block the layer toggle.
    north_arrow_html = """
    <div style="
        position: fixed;
        top: 118px;
        right: 22px;
        z-index: 9998;
        background: transparent;
        padding: 0;
        border: none;
        color: #111;
        font-size: 20px;
        font-weight: 800;
        line-height: 1.05;
        text-align: center;
        text-shadow: 0 0 3px white, 0 0 3px white, 0 0 3px white;
        pointer-events: none;
    ">
        ↑<br>N
    </div>
    """

    fmap.get_root().html.add_child(
        folium.Element(north_arrow_html)
    )

    # Branca LinearColormap legends default to top-right and can overlap the
    # layer control. Move all color-ramp legends to the bottom-right and make
    # them fit inside the visible map width. Keep captions short in
    # map_symbology.py so Folium/Leaflet does not clip the end of the legend.
    legend_position_script = """
    <script>
    (function() {
        function positionColorLegends() {
            var mapEl = document.querySelector('.folium-map') || document.body;
            var mapWidth = mapEl.clientWidth || window.innerWidth || 420;
            var legendWidth = Math.min(430, Math.max(260, mapWidth - 36));
            var legends = Array.prototype.slice.call(
                document.querySelectorAll('.legend.leaflet-control')
            );
            legends.forEach(function(el, i) {
                el.style.position = 'fixed';
                el.style.right = '12px';
                el.style.left = 'auto';
                el.style.top = 'auto';
                el.style.bottom = (18 + i * 72) + 'px';
                el.style.zIndex = '9997';
                el.style.background = 'rgba(255,255,255,0.88)';
                el.style.padding = '3px 5px';
                el.style.border = '1px solid rgba(0,0,0,0.25)';
                el.style.borderRadius = '3px';
                el.style.width = legendWidth + 'px';
                el.style.maxWidth = 'calc(100vw - 28px)';
                el.style.overflow = 'visible';
                el.style.transform = 'scale(0.72)';
                el.style.transformOrigin = 'bottom right';
                el.style.boxShadow = '0 1px 3px rgba(0,0,0,0.2)';
                var svg = el.querySelector('svg');
                if (svg) {
                    svg.setAttribute('width', legendWidth);
                    svg.style.width = '100%';
                    svg.style.maxWidth = '100%';
                    svg.style.overflow = 'visible';
                }
            });
        }
        setTimeout(positionColorLegends, 350);
        setTimeout(positionColorLegends, 1000);
        window.addEventListener('resize', positionColorLegends);
    })();
    </script>
    """

    fmap.get_root().html.add_child(
        folium.Element(legend_position_script)
    )

    return fmap

def make_json_safe_gdf(gdf):
    if gdf is None:
        return None

    gdf = gdf.copy()

    for col in gdf.columns:
        if col == "geometry":
            continue

        gdf[col] = gdf[col].apply(
            lambda x: None if x is None or str(x) in ["nan", "NaT"] else str(x)
        )

    return gdf

def make_map_safe_gdf(
    gdf,
    numeric_cols=None
):
    if gdf is None:
        return None

    if numeric_cols is None:
        numeric_cols = []

    gdf = gdf.copy()

    for col in gdf.columns:
        if col == "geometry":
            continue

        if col in numeric_cols:
            gdf[col] = pd.to_numeric(
                gdf[col],
                errors="coerce"
            ).fillna(0)
        else:
            gdf[col] = gdf[col].apply(
                lambda x: None
                if x is None or str(x) in ["nan", "NaT"]
                else str(x)
            )

    return gdf


def road_class_color(road_class, index=None):

    # Use a larger categorical palette so road classes/types are less likely
    # to share the same color on the map. If an index is supplied by the map
    # builder, the color assignment is stable by sorted category order.
    colors = {
        "Interstate": "red",
        "U.S.": "orange",
        "State Recognized": "blue",
        "County": "green",
        "Common Name": "purple",
        "Other": "gray",
        "Unknown": "black",
    }

    if road_class in colors:
        return colors[road_class]

    palette = [
        "red",
        "blue",
        "green",
        "purple",
        "orange",
        "darkred",
        "cadetblue",
        "darkgreen",
        "darkblue",
        "darkpurple",
        "lightred",
        "beige",
        "pink",
        "lightblue",
        "lightgreen",
        "gray",
        "black",
    ]

    if index is not None:
        return palette[index % len(palette)]

    try:
        idx = sum(ord(ch) for ch in str(road_class))
    except Exception:
        idx = 0

    return palette[idx % len(palette)]

def is_layer_visible(layer_name, default=True):
    visible_layers = st.session_state.get("visible_layers", {})
    return visible_layers.get(layer_name, default)


def export_geojson_bytes(gdf):
    return gdf.to_json().encode("utf-8")

def id_color(value):
    try:
        idx = int(str(value).split("_")[-1])
    except Exception:
        idx = abs(hash(str(value)))

    colors = [
        "red",
        "blue",
        "green",
        "purple",
        "orange",
        "darkred",
        "cadetblue",
        "darkgreen",
        "darkblue",
        "darkpurple",
        "gray",
        "black",
    ]

    return colors[idx % len(colors)]


def clean_for_map(gdf):
    if gdf is None or gdf.empty:
        return None

    gdf = gdf.copy()
    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    if gdf.empty:
        return None

    gdf = gdf.to_crs(4326)

    gdf["geometry"] = gdf.geometry.make_valid()
    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    # TIGER clipping can occasionally produce GeometryCollection features.
    # Explode them before filtering so valid line pieces are not dropped from
    # the crash-density map.
    try:
        gdf = gdf.explode(index_parts=False, ignore_index=True)
        gdf = gdf[gdf.geometry.notna()].copy()
        gdf = gdf[~gdf.geometry.is_empty].copy()
    except Exception:
        pass

    gdf = gdf[
        gdf.geometry.geom_type.isin(
            [
                "Point",
                "MultiPoint",
                "LineString",
                "MultiLineString",
                "Polygon",
                "MultiPolygon",
            ]
        )
    ].copy()

    if gdf.empty:
        return None

    return gdf


def simplify_for_web_map(gdf, tolerance_m=15):
    """Simplify display geometry only. Analysis GeoDataFrames are unchanged."""
    if gdf is None or gdf.empty:
        return gdf

    try:
        geom_types = set(gdf.geometry.geom_type.unique())
        if not any(t in geom_types for t in [
            "LineString",
            "MultiLineString",
            "Polygon",
            "MultiPolygon",
        ]):
            return gdf

        simplified = gdf.to_crs(epsg=3857).copy()
        simplified["geometry"] = simplified.geometry.simplify(
            tolerance=float(tolerance_m),
            preserve_topology=True,
        )
        simplified = simplified[simplified.geometry.notna()].copy()
        simplified = simplified[~simplified.geometry.is_empty].copy()
        return simplified.to_crs(4326)
    except Exception:
        return gdf

def filter_points_to_units(points, units, buffer_m=20):
    if points is None or points.empty:
        return points

    if units is None or units.empty:
        return points.iloc[0:0].copy()

    points_proj = points.to_crs(epsg=3857).copy()
    units_proj = units.to_crs(epsg=3857).copy()

    units_buffer = units_proj.copy()
    units_buffer["geometry"] = units_buffer.geometry.buffer(buffer_m)

    joined = gpd.sjoin(
        points_proj,
        units_buffer[["geometry"]],
        how="inner",
        predicate="intersects"
    )

    filtered = points_proj.loc[
        points_proj.index.isin(joined.index)
    ].copy()

    return filtered.to_crs(points.crs)




def geojson_zip_for_layers(layer_dict):
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for layer_name, gdf in layer_dict.items():
            if gdf is not None and not gdf.empty:

                safe_gdf = make_json_safe_gdf(
                    gdf.to_crs(4326)
                )

                geojson_text = safe_gdf.to_json(
                    na="drop"
                )

                zf.writestr(
                    f"{layer_name}.geojson",
                    geojson_text
                )

    zip_buffer.seek(0)
    return zip_buffer.getvalue()

def make_map(
    boundary=None,
    roads=None,
    roads_class=None,
    signals=None,
    corridors=None,
    spatial_units=None,
    crashes=None,
    density_cmap=None,
    crash_color_settings=None
):
    center_source = None

    for gdf in [
        spatial_units,
        corridors,
        crashes,
        signals,
        roads_class,
        roads,
        boundary
    ]:
        clean_gdf = clean_for_map(gdf)

        if clean_gdf is not None:
            center_source = clean_gdf
            break

    if center_source is not None:
        center_geom = center_source.geometry.union_all().centroid
        location = [center_geom.y, center_geom.x]
        zoom_start = 12
    else:
        # No uploaded data yet. Use a neutral continental-US view only if a
        # caller explicitly renders an empty map. The main app normally shows
        # an upload message instead of rendering this default map.
        location = [39.5, -98.35]
        zoom_start = 4

    fmap = folium.Map(
        location=location,
        zoom_start=zoom_start,
        tiles="CartoDB positron"
    )

    boundary = clean_for_map(boundary)
    boundary = make_json_safe_gdf(boundary)

    if boundary is not None:
        folium.GeoJson(
            boundary,
            name="Selected Boundary",
            show=False,
            style_function=lambda feature: {
                "color": "black",
                "weight": 2,
                "fillOpacity": 0.02,
            },
        ).add_to(fmap)

    roads = simplify_for_web_map(clean_for_map(roads), tolerance_m=15)
    roads = make_json_safe_gdf(roads)

    if roads is not None:
        road_lines = roads[
            roads.geometry.geom_type.isin(
                ["LineString", "MultiLineString"]
            )
        ].copy()

        if not road_lines.empty:
            folium.GeoJson(
                road_lines[["geometry"]].copy(),
                name="Roads",
                show=True,
                style_function=lambda feature: {
                    "color": "#555555",
                    "weight": 2,
                    "opacity": 0.75,
                },
            ).add_to(fmap)


    roads_class = simplify_for_web_map(clean_for_map(roads_class), tolerance_m=15)
    roads_class = make_json_safe_gdf(roads_class)

    if roads_class is not None:
        road_class_lines = roads_class[
            roads_class.geometry.geom_type.isin(
                ["LineString", "MultiLineString"]
            )
        ].copy()

        if not road_class_lines.empty:
            style_col = "RoadStyleClass" if "RoadStyleClass" in road_class_lines.columns else "RoadClass"

            if style_col in road_class_lines.columns:
                categories = sorted(road_class_lines[style_col].fillna("Unknown").astype(str).unique())
                color_lookup = {
                    cat: road_class_color(cat, idx)
                    for idx, cat in enumerate(categories)
                }
                road_class_lines[style_col] = road_class_lines[style_col].fillna("Unknown").astype(str)
            else:
                color_lookup = {"Selected roads": "blue"}
                road_class_lines["RoadStyleClass"] = "Selected roads"
                style_col = "RoadStyleClass"

            # Add one optional Leaflet layer per selected class/type value.
            # This is intentionally only created when the user enables the option
            # in Road Network. If the option is off, the map remains one simple
            # complete Roads layer.
            show_roads_class_type = st.session_state.get(
                "show_roads_class_type",
                False
            )

            for cat in categories:
                sub = road_class_lines[
                    road_class_lines[style_col] == cat
                ].copy()

                if sub.empty:
                    continue

                color = color_lookup.get(
                    str(cat),
                    "blue"
                )

                layer_name = (
                    f"Roads by Class/Type - {cat}"
                )

                road_class_map = sub[
                    [
                        style_col,
                        "geometry"
                    ]
                ].copy()

                folium.GeoJson(
                    road_class_map,
                    name=layer_name,
                    show=show_roads_class_type,
                    style_function=lambda feature, color=color: {
                        "color": color,
                        "weight": 2,
                        "opacity": 1.0,
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=[
                            style_col
                        ],
                        aliases=[
                            "Road class/type"
                        ],
                    ),
                ).add_to(fmap)

            legend_items = "".join(
                '<div style="white-space:nowrap;">'
                '<span style="display:inline-block;'
                'width:11px;height:11px;background:'
                + str(color)
                + ';margin-right:5px;border:1px solid #777;"></span>'
                + str(cat)
                + '</div>'
                for cat, color in color_lookup.items()
            )

            if (
                legend_items
                and st.session_state.get(
                    "road_class_legend_enabled",
                    True
                )
            ):
                legend_html = """
                <div id="road-class-legend" style="
                    display: block;
                    position: fixed;
                    bottom: 45px;
                    left: 42px;
                    z-index: 9999;
                    background: rgba(255, 255, 255, 0.94);
                    padding: 7px 9px;
                    border: 1px solid #888;
                    border-radius: 4px;
                    font-size: 11px;
                    max-height: 240px;
                    max-width: 260px;
                    overflow-y: auto;
                    box-shadow: 0 1px 4px rgba(0,0,0,0.25);
                ">
                    <b>Road Class/Type</b><br>
                    {legend_items}
                </div>
                """.replace(
                    "{legend_items}",
                    legend_items
                )

                fmap.get_root().html.add_child(
                    folium.Element(
                        legend_html
                    )
                )

                # Road class/type legend is controlled only by the optional
                # "Show Road Class/Type legend" checkbox. It is not automatically
                # hidden when road class layers are unchecked, so users can keep
                # the color reference visible across Intersection, Corridor, and
                # Segment maps.

    corridors = clean_for_map(corridors)
    corridors = make_json_safe_gdf(corridors)

    if corridors is not None:
        tooltip_fields = [
            c for c in [
                "CorridorID",
                "corridor_id",
                "Route",
                "SignalCnt",
                "SignalRowCnt",
                "RoadCnt",
                "Method",
                "CrashCount"
            ]
            if c in corridors.columns
        ]

        # Keep all corridors in one Leaflet overlay. Individual corridor popups/tooltips
        # remain available, but the layer control stays compact and fast.
        def corridor_color(corridor_id):
            colors = [
                "#e6194b",
                "#3cb44b",
                "#4363d8",
                "#f58231",
                "#911eb4",
                "#46f0f0",
                "#f032e6",
                "#008080",
                "#9a6324",
                "#800000",
                "#808000",
                "#000075",
                "#808080"
            ]

            try:
                idx = int(corridor_id) - 1
            except Exception:
                idx = abs(hash(str(corridor_id)))

            return colors[idx % len(colors)]
        
        folium.GeoJson(
            corridors,
            name="Corridors",
            style_function=lambda feature: {
                "color": corridor_color(
                    feature["properties"].get(
                        "CorridorID",
                        feature["properties"].get(
                            "Route",
                            ""
                        )
                    )
                ),
                "fillColor": corridor_color(
                    feature["properties"].get(
                        "CorridorID",
                        feature["properties"].get(
                            "Route",
                            ""
                        )
                    )
                ),
                "weight": 2,
                "fillOpacity": 0.16,
                "opacity": 0.85,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_fields
            ) if tooltip_fields else None,
        ).add_to(fmap)

    spatial_units = clean_for_map(spatial_units)
        
    if spatial_units is not None and not spatial_units.empty:

        spatial_units_plot = spatial_units.to_crs(
            epsg=4326
        ).copy()

        spatial_units_plot = make_map_safe_gdf(
            spatial_units_plot,
            numeric_cols=[
                "CrashDensity",
                "CrashCount",
                "Length_Miles",
                "Area_SqMi"
            ]
        )

        spatial_units_group = folium.FeatureGroup(
            name="Spatial Units - Crash Density",
            show=True
        )

        def style_spatial_unit(feature):

            density = feature["properties"].get(
                "CrashDensity",
                0
            )

            try:

                density = float(
                    density
                )

            except Exception:

                density = 0.0

            if density_cmap is not None:

                color = density_cmap(
                    density
                )

            else:

                color = "purple"

            return {
                "color": color,
                "fillColor": color,
                "weight": 2,
                "fillOpacity": 0.45,
                "opacity": 0.85,
            }

        tooltip_fields = [
            c for c in [
                "UnitID",
                "UnitType",
                "CrashCount",
                "CrashDensity",
                "Length_Miles",
                "Area_SqMi",
                "IntersectionID",
                "SegmentID",
                "CorridorID",
                "Route",
                "FULLNAME",
                "RouteName_Calc",
                "RoadName1",
                "RoadName2"
            ]
            if c in spatial_units_plot.columns
        ]

        # Keep the browser GeoJSON light and predictable. TIGER road files can
        # carry many source attributes; only send the fields needed for popups,
        # styling, and geometry to Folium.
        map_cols = ["geometry"] + [
            c for c in tooltip_fields if c in spatial_units_plot.columns
        ]
        spatial_units_plot = spatial_units_plot[
            list(dict.fromkeys(map_cols))
        ].copy()

        folium.GeoJson(
            spatial_units_plot,
            name="Spatial Units - Crash Density",
            style_function=style_spatial_unit,
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_fields,
                localize=True
            ) if tooltip_fields else None,
        ).add_to(spatial_units_group)

        spatial_units_group.add_to(fmap)
        

    signals = clean_for_map(signals)

    if signals is not None:
        signals_for_markers = signals.copy()

        if (
            "SignalID" in signals_for_markers.columns
            and "Route" in signals_for_markers.columns
        ):
            route_lookup = (
                signals_for_markers
                .dropna(subset=["Route"])
                .assign(Route=lambda df: df["Route"].astype(str).str.strip())
                .groupby("SignalID")["Route"]
                .apply(
                    lambda values: ", ".join(
                        sorted(
                            {
                                value
                                for value in values
                                if value and value.upper() not in ["NONE", "NAN"]
                            }
                        )
                    )
                )
            )

            signals_for_markers = (
                signals_for_markers
                .drop_duplicates(subset=["SignalID"])
                .copy()
            )

            signals_for_markers["AssignedRoutes"] = (
                signals_for_markers["SignalID"]
                .map(route_lookup)
                .fillna("")
            )

        elif "SignalID" in signals_for_markers.columns:
            signals_for_markers = (
                signals_for_markers
                .drop_duplicates(subset=["SignalID"])
                .copy()
            )

        else:
            signals_for_markers["_signal_geom_wkb"] = (
                signals_for_markers.geometry.to_wkb()
            )
            signals_for_markers = (
                signals_for_markers
                .drop_duplicates(subset=["_signal_geom_wkb"])
                .drop(columns=["_signal_geom_wkb"])
            )

        signals_for_markers = make_json_safe_gdf(
            signals_for_markers
        )

        signal_group = folium.FeatureGroup(
            name="Signals"
        )

        for _, row in signals_for_markers.iterrows():
            geom = row.geometry

            if geom.geom_type == "Point":
                popup_text = ""

                if "SignalID" in row.index:
                    popup_text += f"SignalID: {row['SignalID']}<br>"

                if "City" in row.index:
                    popup_text += f"City: {row['City']}<br>"

                if "AssignedRoutes" in row.index and row["AssignedRoutes"]:
                    popup_text += f"Routes: {row['AssignedRoutes']}<br>"

                folium.Marker(
                    location=[
                        geom.y,
                        geom.x
                    ],
                    icon=folium.DivIcon(
                        html="""
                        <div style="font-size:18px;">🚦</div>
                        """
                    ),
                    popup=popup_text,
                ).add_to(signal_group)

        signal_group.add_to(fmap)

    crashes = clean_for_map(crashes)
    crashes = make_json_safe_gdf(crashes)

    if crashes is not None:
        crash_group = folium.FeatureGroup(
            name="Crashes"
        )

        crash_color_settings = crash_color_settings or {"enabled": False}
        if crash_color_settings.get("enabled") and crash_color_settings.get("field") in crashes.columns:
            crash_color_settings["color_lookup"] = crash_color_settings.get("color_lookup") or categorical_color_lookup(
                crashes[crash_color_settings.get("field")].fillna("Unknown")
            )

        for _, row in crashes.iterrows():
            geom = row.geometry

            if geom.geom_type == "Point":
                popup_text = ""

                if "SourceCrashID" in row.index:
                    popup_text += (
                        f"Case ID: "
                        f"{row['SourceCrashID']}<br>"
                    )

                if "CrashID" in row.index:
                    popup_text += (
                        f"App ID: "
                        f"{row['CrashID']}<br>"
                    )

                if "UnitID" in row.index:
                    popup_text += (
                        f"UnitID: "
                        f"{row['UnitID']}<br>"
                    )

                marker_color, color_value = crash_marker_style(row, crash_color_settings)
                if color_value is not None:
                    popup_text += f"{crash_color_settings.get('field')}: {color_value}<br>"

                folium.CircleMarker(
                    location=[
                        geom.y,
                        geom.x
                    ],
                    radius=4,
                    color=marker_color,
                    weight=1.0,
                    fill=True,
                    fill_color=marker_color,
                    fill_opacity=0.75,
                    popup=popup_text,
                ).add_to(crash_group)

        crash_group.add_to(fmap)

        if crash_color_settings.get("enabled"):
            fmap = add_categorical_legend(
                fmap,
                f"Crashes by {crash_color_settings.get('field')}",
                crash_color_settings.get("color_lookup"),
                element_id="crash-color-legend",
            )

    fmap.get_root().header.add_child(
        folium.Element(
            """
            <style>
            .leaflet-control-layers {
                font-size: 11px !important;
                max-width: 210px !important;
            }
            .leaflet-control-layers-expanded {
                padding: 4px 6px !important;
            }
            </style>
            """
        )
    )

    folium.LayerControl(
        collapsed=True,
        position="topright"
    ).add_to(fmap)

    return fmap

