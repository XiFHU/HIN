# modules/visualization.py

import folium


def add_layer(
    fmap,
    gdf,
    name,
    color="blue",
    weight=3,
    fill_opacity=0.25
):
    """
    Generic safe Folium layer renderer.
    """

    if gdf is None or gdf.empty:
        return fmap

    gdf = gdf.to_crs(4326).copy()

    geom_types = set(gdf.geometry.geom_type)

    if geom_types.issubset({"Point", "MultiPoint"}):

        group = folium.FeatureGroup(name=name)

        for _, row in gdf.iterrows():

            geom = row.geometry

            if geom.geom_type == "Point":

                folium.CircleMarker(
                    location=[
                        geom.y,
                        geom.x
                    ],
                    radius=4,
                    color=color,
                    weight=1,
                    fill=True,
                    fill_opacity=0.8,
                ).add_to(group)

        group.add_to(fmap)

    elif geom_types.issubset({"LineString", "MultiLineString"}):

        folium.GeoJson(
            gdf,
            name=name,
            style_function=lambda feature: {
                "color": color,
                "weight": weight,
                "opacity": 0.9,
            },
        ).add_to(fmap)

    else:

        folium.GeoJson(
            gdf,
            name=name,
            style_function=lambda feature: {
                "color": color,
                "fillColor": color,
                "weight": weight,
                "fillOpacity": fill_opacity,
            },
        ).add_to(fmap)

    return fmap
