"""Folium map utilities for the HIN Streamlit app."""

import io
import zipfile

import folium
import folium.plugins
import pandas as pd
import streamlit as st
import geopandas as gpd

from .layer_manager import is_layer_visible

def add_map_elements(fmap):

    folium.plugins.MeasureControl(
        position="bottomleft",
        primary_length_unit="miles",
        secondary_length_unit="feet"
    ).add_to(fmap)

    north_arrow_html = """
    <div style="
        position: fixed;
        top: 80px;
        right: 30px;
        z-index: 9999;
        background: white;
        padding: 8px;
        border: 2px solid black;
        font-size: 22px;
        font-weight: bold;
        text-align: center;
    ">
        ↑<br>N
    </div>
    """

    fmap.get_root().html.add_child(
        folium.Element(north_arrow_html)
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


def road_class_color(road_class):

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
        "gray",
        "black",
    ]

    try:
        idx = abs(hash(str(road_class)))
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
    signals=None,
    corridors=None,
    spatial_units=None,
    crashes=None,
    density_cmap=None
):
    center_source = None

    for gdf in [
        spatial_units,
        corridors,
        crashes,
        signals,
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
        location = [39.7, -104.9]
        zoom_start = 10

    fmap = folium.Map(
        location=location,
        zoom_start=zoom_start,
        tiles="OpenStreetMap"
    )

    boundary = clean_for_map(boundary)
    boundary = make_json_safe_gdf(boundary)

    if boundary is not None and is_layer_visible("Boundary"):
        folium.GeoJson(
            boundary,
            name="Selected Boundary",
            style_function=lambda feature: {
                "color": "black",
                "weight": 2,
                "fillOpacity": 0.02,
            },
        ).add_to(fmap)

    roads = clean_for_map(roads)
    roads = make_json_safe_gdf(roads)

    if roads is not None and is_layer_visible("Roads"):
        road_lines = roads[
            roads.geometry.geom_type.isin(
                ["LineString", "MultiLineString"]
            )
        ].copy()

        if not road_lines.empty:

            if "RoadClass" in road_lines.columns:
                groups = road_lines.groupby("RoadClass")
            else:
                groups = [("Unknown", road_lines)]

            for road_class, sub in groups:

                sub = make_json_safe_gdf(sub)

                folium.GeoJson(
                    sub,
                    name=f"{road_class}",
                    style_function=lambda feature, road_class=road_class: {
                        "color": road_class_color(road_class),
                        "weight": 3,
                        "opacity": 0.9,
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=[
                            c for c in [
                                "FULLNAME",
                                "RouteName_Calc",
                                "FromMile",
                                "ToMile",
                                "RoadClass",
                                "RoadType"
                            ]
                            if c in sub.columns
                        ]
                    )
                ).add_to(fmap)

    corridors = clean_for_map(corridors)
    corridors = make_json_safe_gdf(corridors)

    if corridors is not None and is_layer_visible("Corridors"):
        id_field = None

        if "CorridorID" in corridors.columns:
            id_field = "CorridorID"
        elif "corridor_id" in corridors.columns:
            id_field = "corridor_id"

        if id_field is not None:
            for corridor_id, sub in corridors.groupby(id_field):
                color = id_color(corridor_id)

                sub = make_json_safe_gdf(sub)

                tooltip_fields = [
                    c for c in [
                        id_field,
                        "Route",
                        "SignalCnt",
                        "CrashCount"
                    ]
                    if c in sub.columns
                ]

                folium.GeoJson(
                    sub,
                    name=f"Corridor {corridor_id}",
                    style_function=lambda feature, color=color: {
                        "color": color,
                        "fillColor": color,
                        "weight": 3,
                        "fillOpacity": 0.25,
                        "opacity": 0.9,
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=tooltip_fields
                    ) if tooltip_fields else None,
                ).add_to(fmap)

        else:
            folium.GeoJson(
                corridors,
                name="Corridors",
                style_function=lambda feature: {
                    "color": "purple",
                    "fillColor": "purple",
                    "weight": 3,
                    "fillOpacity": 0.25,
                },
            ).add_to(fmap)

    spatial_units = clean_for_map(spatial_units)

    if spatial_units is not None and not spatial_units.empty and is_layer_visible("Spatial Units"):

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
                "weight": 4,
                "fillOpacity": 0.55,
                "opacity": 0.9,
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
    signals = make_json_safe_gdf(signals)

    if signals is not None and is_layer_visible("Signals"):
        signal_group = folium.FeatureGroup(
            name="Signals"
        )

        for _, row in signals.iterrows():
            geom = row.geometry

            if geom.geom_type == "Point":
                popup_text = ""

                if "SignalID" in row.index:
                    popup_text += f"SignalID: {row['SignalID']}<br>"

                if "City" in row.index:
                    popup_text += f"City: {row['City']}<br>"

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

    if crashes is not None and is_layer_visible("Crashes"):
        crash_group = folium.FeatureGroup(
            name="Crashes"
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

                folium.CircleMarker(
                    location=[
                        geom.y,
                        geom.x
                    ],
                    radius=4,
                    color="black",
                    weight=1,
                    fill=True,
                    fill_opacity=0.8,
                    popup=popup_text,
                ).add_to(crash_group)

        crash_group.add_to(fmap)

    fmap.get_root().header.add_child(
        folium.Element(
            """
            <style>
            .leaflet-control-layers {
                font-size: 10px !important;
                max-width: 170px !important;
            }
            .leaflet-control-layers-toggle {
                width: 28px !important;
                height: 28px !important;
                background-size: 18px 18px !important;
            }
            .leaflet-control-layers-expanded {
                padding: 4px 6px !important;
                line-height: 1.15 !important;
            }
            .leaflet-control-layers label {
                margin-bottom: 1px !important;
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

