# modules/roads.py

import geopandas as gpd


ROUTE_TYPE_NAMES = {
    "C": "County",
    "I": "Interstate",
    "M": "Common Name",
    "O": "Other",
    "S": "State Recognized",
    "U": "U.S.",
}


MTFCC_TYPE_NAMES = {
    "S1100": "Primary Road",
    "S1200": "Secondary Road",
    "S1400": "Local / Neighborhood Road",
    "S1500": "Vehicular Trail",
    "S1630": "Ramp",
    "S1640": "Service Drive",
    "S1710": "Walkway / Pedestrian Trail",
    "S1720": "Stairway",
    "S1730": "Alley",
    "S1740": "Private Road",
    "S1750": "Internal Census Use",
    "S1780": "Parking Lot Road",
    "S1820": "Bike Path / Trail",
    "S1830": "Bridle Path",
}


DEFAULT_EXCLUDE_ROUTE_CLASSES = [
    "Other",
]


def check_required_columns(gdf, required_cols, layer_name):
    missing = [
        c for c in required_cols
        if c not in gdf.columns
    ]

    if missing:
        raise ValueError(
            f"{layer_name} is missing required columns: {missing}"
        )


def route_type_name(rttyp):
    if rttyp is None:
        return "Unknown"

    rttyp = str(rttyp).strip().upper()

    if rttyp == "" or rttyp == "NAN" or rttyp == "NONE":
        return "Unknown"

    return ROUTE_TYPE_NAMES.get(
        rttyp,
        "Unknown"
    )


def mtfcc_type_name(mtfcc):
    if mtfcc is None:
        return "Unknown"

    mtfcc = str(mtfcc).strip().upper()

    if mtfcc == "" or mtfcc == "NAN" or mtfcc == "NONE":
        return "Unknown"

    return MTFCC_TYPE_NAMES.get(
        mtfcc,
        "Unknown"
    )


def add_road_class_fields(roads_gdf):
    roads = roads_gdf.copy()

    if "RTTYP" in roads.columns:
        roads["RoadClass"] = (
            roads["RTTYP"]
            .apply(route_type_name)
        )
    else:
        roads["RoadClass"] = "Unknown"

    if "MTFCC" in roads.columns:
        roads["RoadType"] = (
            roads["MTFCC"]
            .apply(mtfcc_type_name)
        )
    else:
        roads["RoadType"] = "Unknown"

    return roads


def get_city_names(places_gdf):
    check_required_columns(
        places_gdf,
        ["NAME"],
        "PLACE file"
    )

    return sorted(
        places_gdf["NAME"]
        .dropna()
        .astype(str)
        .unique()
    )


def get_city_boundary(places_gdf, city_name):
    check_required_columns(
        places_gdf,
        ["NAME"],
        "PLACE file"
    )

    city = places_gdf[
        places_gdf["NAME"].astype(str) == str(city_name)
    ].copy()

    if city.empty:
        raise ValueError(
            f"City not found: {city_name}"
        )

    return city


def clip_city_roads(roads_gdf, places_gdf, city_name):
    city = get_city_boundary(
        places_gdf,
        city_name
    )

    if roads_gdf.crs != city.crs:
        city = city.to_crs(
            roads_gdf.crs
        )

    city_geom = city.geometry.union_all()

    clipped = roads_gdf[
        roads_gdf.intersects(city_geom)
    ].copy()

    clipped["geometry"] = (
        clipped.geometry.intersection(city_geom)
    )

    clipped = clipped[
        clipped.geometry.notna()
    ].copy()

    clipped = clipped[
        ~clipped.geometry.is_empty
    ].copy()

    clipped = add_road_class_fields(
        clipped
    )

    return clipped


def get_road_classes(roads_gdf):
    roads = add_road_class_fields(
        roads_gdf
    )

    classes = sorted(
        roads["RoadClass"]
        .dropna()
        .astype(str)
        .unique()
    )

    return classes


def get_default_road_class_labels(roads_gdf):
    all_labels = get_road_classes(
        roads_gdf
    )

    default_labels = [
        label for label in all_labels
        if label not in DEFAULT_EXCLUDE_ROUTE_CLASSES
    ]

    return default_labels


def filter_road_classes(roads_gdf, selected_class_labels):
    roads = add_road_class_fields(
        roads_gdf
    )

    if not selected_class_labels:
        return roads.iloc[0:0].copy()

    filtered = roads[
        roads["RoadClass"]
        .astype(str)
        .isin(selected_class_labels)
    ].copy()

    return filtered


def clean_road_geometries(roads_gdf):
    roads = roads_gdf.copy()

    roads = roads[
        roads.geometry.notna()
    ].copy()

    roads = roads[
        ~roads.geometry.is_empty
    ].copy()

    roads = roads[
        roads.geometry.geom_type.isin(
            [
                "LineString",
                "MultiLineString"
            ]
        )
    ].copy()

    roads = add_road_class_fields(
        roads
    )

    return roads


def get_city_names_in_road_area(places_gdf, roads_gdf):
    check_required_columns(
        places_gdf,
        ["NAME"],
        "PLACE file"
    )

    if places_gdf.crs != roads_gdf.crs:
        roads_gdf = roads_gdf.to_crs(
            places_gdf.crs
        )

    road_area = (
        roads_gdf
        .geometry
        .union_all()
        .convex_hull
    )

    places_in_area = places_gdf[
        places_gdf.intersects(road_area)
    ].copy()

    return sorted(
        places_in_area["NAME"]
        .dropna()
        .astype(str)
        .unique()
    )
