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


# =====================================================
# OSM road download helpers
# =====================================================

OSM_FUNCTIONAL_CLASSES = [
    "Expressway",
    "Major Arterial",
    "Minor Arterial",
    "Major Collector",
    "Minor Collector",
    "Local Road",
    "Omit From Analysis",
]

DEFAULT_OSM_HIGHWAY_CLASS_MAPPING = {
    "motorway": "Expressway",
    "motorway_link": "Expressway",
    "trunk": "Major Arterial",
    "trunk_link": "Major Arterial",
    "primary": "Major Arterial",
    "primary_link": "Major Arterial",
    "secondary": "Minor Arterial",
    "secondary_link": "Minor Arterial",
    "tertiary": "Major Collector",
    "tertiary_link": "Major Collector",
    "residential": "Local Road",
    "living_street": "Local Road",
    "unclassified": "Local Road",
    "road": "Local Road",
    "service": "Omit From Analysis",
}


def _safe_union(geoseries):
    """Return a single geometry while supporting older/newer GeoPandas."""
    try:
        return geoseries.union_all()
    except Exception:
        return geoseries.unary_union


def _first_text_value(value):
    """Convert OSM scalar/list values to a readable string."""
    if value is None:
        return ""

    try:
        if value != value:  # NaN
            return ""
    except Exception:
        pass

    if isinstance(value, (list, tuple, set)):
        for item in value:
            text = _first_text_value(item)
            if text:
                return text
        return ""

    text = str(value).strip()

    if text.lower() in ["", "nan", "none"]:
        return ""

    return text


def normalize_osm_highway_value(value):
    """Normalize OSM highway values for classification mapping."""
    text = _first_text_value(value)
    return text.lower().strip()


def _osm_route_name(row):
    for col in ["name", "ref"]:
        if col in row.index:
            text = _first_text_value(row[col])
            if text:
                return text

    highway = _first_text_value(row.get("OSMHighway", ""))
    osmid = _first_text_value(row.get("osmid", ""))

    if osmid:
        return f"OSM {highway or 'road'} {osmid}"

    return "OSM unnamed road"


def _osm_query_candidates(place_query):
    """Return simple fallback OSM/Nominatim query variants.

    Nominatim can be sensitive to punctuation and country wording. This keeps
    the UI simple while trying the same city in a few common forms.
    """
    raw = " ".join(str(place_query or "").replace("\n", " ").split()).strip()
    if not raw:
        return []

    candidates = []

    def add(value):
        value = " ".join(str(value or "").split()).strip(" ,")
        if value and value.lower() not in [c.lower() for c in candidates]:
            candidates.append(value)

    add(raw)

    # Common cleanup variants.
    cleaned = raw.replace(", USA", "").replace(", U.S.A.", "").replace(", United States", "")
    add(cleaned)

    # Expand/contract Colorado for local use cases without changing other states.
    add(cleaned.replace(", CO", ", Colorado"))
    add(cleaned.replace(", Colorado", ", CO"))

    if "colorado" in cleaned.lower() or cleaned.lower().endswith(", co"):
        city = cleaned.split(",")[0].strip()
        if city:
            add(f"{city}, Arapahoe County, Colorado, USA")
            add(f"{city}, Colorado, United States")
            add(f"City of {city}, Colorado, USA")

    return candidates


def fetch_osm_roads_for_place(place_query, network_type="drive"):
    """Download OSM roads for a geocoded place name using OSMnx.

    Returns
    -------
    roads : GeoDataFrame
        OSM drive-network edges in EPSG:4326.
    boundary : GeoDataFrame
        Geocoded place boundary in EPSG:4326.
    """
    if place_query is None or not str(place_query).strip():
        raise ValueError("Enter a study area place name before downloading OSM roads.")

    try:
        import osmnx as ox
    except Exception as exc:
        raise ImportError(
            "OSMnx is required for the no-upload OSM road option. "
            "Install the requirements.txt package list and try again."
        ) from exc

    errors = []

    for query in _osm_query_candidates(place_query):
        try:
            boundary = ox.geocode_to_gdf(query).to_crs(4326)

            if boundary.empty:
                errors.append(f"{query}: no boundary returned")
                continue

            boundary_geom = _safe_union(boundary.geometry)

            graph = ox.graph_from_polygon(
                boundary_geom,
                network_type=network_type,
                simplify=True,
                retain_all=False,
                truncate_by_edge=True,
            )

            roads = ox.graph_to_gdfs(
                graph,
                nodes=False,
                fill_edge_geometry=True,
            ).reset_index()

            if roads.empty:
                errors.append(f"{query}: no roads returned")
                continue

            roads = roads.to_crs(4326)
            roads = roads[roads.geometry.notna()].copy()
            roads = roads[~roads.geometry.is_empty].copy()
            roads = roads[
                roads.geometry.geom_type.isin(["LineString", "MultiLineString"])
            ].copy()

            if roads.empty:
                errors.append(f"{query}: no usable road geometries")
                continue

            roads["OSMHighway"] = roads["highway"].apply(normalize_osm_highway_value)
            roads["OSMEdgeID"] = [f"OSM_EDGE_{i + 1}" for i in range(len(roads))]
            roads["RouteNameOSM"] = roads.apply(_osm_route_name, axis=1)
            roads["RoadType"] = roads["OSMHighway"].fillna("Unknown")

            try:
                boundary_for_clip = boundary[["geometry"]].copy()
                if boundary_for_clip.crs != roads.crs:
                    boundary_for_clip = boundary_for_clip.to_crs(roads.crs)
                boundary_geom = _safe_union(boundary_for_clip.geometry)
                roads = roads[roads.intersects(boundary_geom)].copy()
            except Exception:
                pass

            if roads.empty:
                errors.append(f"{query}: roads were empty after clipping")
                continue

            return roads.reset_index(drop=True), boundary

        except Exception as exc:
            errors.append(f"{query}: {exc}")

    detail = " | ".join(errors[-3:]) if errors else "No OSM/Nominatim boundary was found."
    raise ValueError(
        "Unable to download OSM roads for the study area. Tried query variants. "
        + detail
    )


def suggest_osm_places(place_query, limit=8):
    """Return candidate OSM/Nominatim place matches for a user-entered query.

    This is used only for UI suggestions before downloading roads. It does not
    download the road network. If the first query returns nothing, the function
    tries a few simple variants such as removing USA or expanding CO/Colorado.
    """
    if place_query is None or not str(place_query).strip():
        return []

    try:
        import requests
    except Exception:
        return []

    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        "User-Agent": "Corridor-HIN-Streamlit-App/1.0"
    }

    suggestions = []
    seen = set()

    for query in _osm_query_candidates(place_query):
        params = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": int(limit),
        }

        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            continue

        for item in data:
            display_name = str(item.get("display_name", "")).strip()
            if not display_name:
                continue

            key = display_name.lower()
            if key in seen:
                continue
            seen.add(key)

            suggestions.append(
                {
                    "display_name": display_name,
                    "osm_type": item.get("osm_type", ""),
                    "osm_id": item.get("osm_id", ""),
                    "class": item.get("class", ""),
                    "type": item.get("type", ""),
                    "lat": item.get("lat", ""),
                    "lon": item.get("lon", ""),
                }
            )

        if len(suggestions) >= int(limit):
            break

    return suggestions[:int(limit)]


def apply_osm_highway_mapping(roads_gdf, highway_mapping):
    """Apply an OSM highway-to-functional-class mapping to roads."""
    roads = roads_gdf.copy()

    if "OSMHighway" not in roads.columns:
        if "highway" in roads.columns:
            roads["OSMHighway"] = roads["highway"].apply(normalize_osm_highway_value)
        else:
            roads["OSMHighway"] = "unknown"

    mapping = {
        str(k).strip().lower(): str(v)
        for k, v in dict(highway_mapping or {}).items()
    }

    roads["RoadClass"] = (
        roads["OSMHighway"]
        .astype(str)
        .str.lower()
        .map(mapping)
        .fillna("Local Road")
    )

    # FunctionalClass is a user-facing alias for the OSM-derived RoadClass.
    # Keeping both names avoids confusion in the Road Network Filter while
    # preserving compatibility with existing downstream map/style code.
    roads["FunctionalClass"] = roads["RoadClass"]

    roads["RoadType"] = roads["OSMHighway"].fillna("Unknown").astype(str)
    roads["RoadStyleClass"] = roads["RoadClass"].fillna("Unknown").astype(str)

    return roads
