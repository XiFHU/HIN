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
    """Return generic OSM/Nominatim query variants without assuming a state.

    This app is not Colorado-only.  For a short city-only input such as
    "Aurora", the app should search globally and return a list of possible
    places for the user to choose from.  The function therefore only normalizes
    the user's text and tries safe variants; it never appends a state, county,
    or country that the user did not provide.
    """
    raw = " ".join(str(place_query or "").replace("\n", " ").split()).strip()
    if not raw:
        return []

    candidates = []
    seen = set()

    def add(value):
        value = " ".join(str(value or "").split()).strip(" ,")
        key = value.lower()
        if value and key not in seen:
            candidates.append(value)
            seen.add(key)

    add(raw)
    add(raw.title())

    # Country-word cleanup/expansion based only on text already entered.
    cleaned = raw
    for suffix in [
        ", USA", ", U.S.A.", ", United States",
        ", usa", ", u.s.a.", ", united states",
    ]:
        cleaned = cleaned.replace(suffix, "")
    cleaned = cleaned.strip(" ,")
    add(cleaned)
    add(cleaned.title())

    add(raw.replace(", US", ", United States"))
    add(raw.replace(", U.S.", ", United States"))
    add(raw.replace(", UK", ", United Kingdom"))
    add(raw.replace(", UAE", ", United Arab Emirates"))

    # Generic city wording can help Nominatim, but still does not force a state.
    if "," not in cleaned:
        add(f"City of {cleaned}")
        add(f"City of {cleaned.title()}")

    return candidates



def _normalize_bbox_dict(value):
    """Return bbox dict with south/north/west/east floats, or None."""
    if not value:
        return None

    try:
        if isinstance(value, dict):
            south = float(value["south"])
            north = float(value["north"])
            west = float(value["west"])
            east = float(value["east"])
        else:
            vals = [float(v) for v in value]
            if len(vals) != 4:
                return None

            # Nominatim boundingbox order is [south, north, west, east].
            # Photon extent order is usually [west, north, east, south].
            a, b, c, d = vals

            if abs(a) <= 90 and abs(b) <= 90 and abs(c) <= 180 and abs(d) <= 180:
                south, north, west, east = a, b, c, d
            else:
                west, north, east, south = a, b, c, d

        if south > north:
            south, north = north, south
        if west > east:
            west, east = east, west

        if south == north or west == east:
            return None

        return {
            "south": south,
            "north": north,
            "west": west,
            "east": east,
        }
    except Exception:
        return None


def _bbox_from_point(lat, lon, buffer_degrees=0.08):
    """Create a small bbox around a geocoded point as a last-resort fallback."""
    try:
        lat = float(lat)
        lon = float(lon)
    except Exception:
        return None

    return {
        "south": lat - buffer_degrees,
        "north": lat + buffer_degrees,
        "west": lon - buffer_degrees,
        "east": lon + buffer_degrees,
    }


def _boundary_from_bbox(bbox):
    """Create an EPSG:4326 rectangular boundary GeoDataFrame from a bbox."""
    from shapely.geometry import box

    bbox = _normalize_bbox_dict(bbox)
    if not bbox:
        return None

    return gpd.GeoDataFrame(
        {
            "BoundarySource": ["OSM geocoder bounding box"],
        },
        geometry=[
            box(
                bbox["west"],
                bbox["south"],
                bbox["east"],
                bbox["north"],
            )
        ],
        crs="EPSG:4326",
    )


def _finalize_osm_roads(roads):
    """Clean OSMnx edge GeoDataFrame and add fields used by the app."""
    if roads is None or roads.empty:
        return roads

    roads = roads.to_crs(4326)
    roads = roads[roads.geometry.notna()].copy()
    roads = roads[~roads.geometry.is_empty].copy()
    roads = roads[
        roads.geometry.geom_type.isin(["LineString", "MultiLineString"])
    ].copy()

    if roads.empty:
        return roads

    if "highway" in roads.columns:
        roads["OSMHighway"] = roads["highway"].apply(normalize_osm_highway_value)
    else:
        roads["OSMHighway"] = "unknown"

    roads["OSMEdgeID"] = [f"OSM_EDGE_{i + 1}" for i in range(len(roads))]
    roads["RouteNameOSM"] = roads.apply(_osm_route_name, axis=1)
    roads["RoadType"] = roads["OSMHighway"].fillna("Unknown")

    return roads


def _download_osm_roads_from_bbox(bbox, network_type="drive"):
    """Download OSM roads from a bbox without calling Nominatim again."""
    try:
        import osmnx as ox
    except Exception as exc:
        raise ImportError(
            "OSMnx is required for the no-upload OSM road option. "
            "Install the requirements.txt package list and try again."
        ) from exc

    bbox = _normalize_bbox_dict(bbox)
    if not bbox:
        raise ValueError("No usable bounding box was available for this OSM place.")

    west = bbox["west"]
    south = bbox["south"]
    east = bbox["east"]
    north = bbox["north"]

    graph = None
    errors = []

    # OSMnx 2.x uses one bbox tuple. Older OSMnx uses north/south/east/west.
    try:
        graph = ox.graph_from_bbox(
            (west, south, east, north),
            network_type=network_type,
            simplify=True,
            retain_all=False,
            truncate_by_edge=True,
        )
    except Exception as exc:
        errors.append(str(exc))

    if graph is None:
        try:
            graph = ox.graph_from_bbox(
                north,
                south,
                east,
                west,
                network_type=network_type,
                simplify=True,
                retain_all=False,
                truncate_by_edge=True,
            )
        except Exception as exc:
            errors.append(str(exc))

    if graph is None:
        raise ValueError("Unable to download roads by bounding box. " + " | ".join(errors[-2:]))

    roads = ox.graph_to_gdfs(
        graph,
        nodes=False,
        fill_edge_geometry=True,
    ).reset_index()

    roads = _finalize_osm_roads(roads)

    if roads is None or roads.empty:
        raise ValueError("No usable OSM road geometries were returned for the selected bounding box.")

    boundary = _boundary_from_bbox(bbox)

    try:
        boundary_geom = _safe_union(boundary.geometry)
        roads = roads[roads.intersects(boundary_geom)].copy()
    except Exception:
        pass

    if roads.empty:
        raise ValueError("Roads were empty after clipping to the selected bounding box.")

    return roads.reset_index(drop=True), boundary


def fetch_osm_roads_for_place(place_query, network_type="drive", place_info=None):
    """Download OSM roads for a selected place.

    If the user selected a dropdown suggestion that includes a bounding box,
    this function downloads roads from that bbox first. That avoids a second
    Nominatim call during Download OSM roads, which helps prevent HTTP 429.
    If no bbox is available, it falls back to the original OSMnx geocode method.
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

    bbox = None
    if isinstance(place_info, dict):
        bbox = _normalize_bbox_dict(
            place_info.get("bbox")
            or place_info.get("boundingbox")
        )

        if bbox is None:
            bbox = _bbox_from_point(
                place_info.get("lat"),
                place_info.get("lon"),
            )

    if bbox is not None:
        try:
            return _download_osm_roads_from_bbox(
                bbox,
                network_type=network_type,
            )
        except Exception as exc:
            errors.append(f"bbox download: {exc}")

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

            roads = _finalize_osm_roads(roads)

            if roads.empty:
                errors.append(f"{query}: no usable road geometries")
                continue

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


def _osm_suggestion_search_requests(place_query, limit=20):
    """Build one global Nominatim suggestion request.

    A single q=Aurora request can still return multiple global matches, such
    as Aurora CO, Aurora IL, and other places. Sending only one request avoids
    triggering Nominatim HTTP 429 as easily.
    """
    raw = " ".join(str(place_query or "").replace("\n", " ").split()).strip()

    if not raw:
        return []

    return [
        {
            "q": raw,
            "format": "jsonv2",
            "addressdetails": 1,
            "extratags": 1,
            "namedetails": 1,
            "dedupe": 0,
            "limit": int(limit),
            "accept-language": "en",
        }
    ]


def _format_osm_suggestion_label(item):
    """Create a compact city / county / state / country dropdown label."""
    display_name = str(item.get("display_name", "")).strip()
    address = item.get("address") or {}

    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("hamlet")
        or address.get("locality")
        or item.get("name")
        or ""
    )

    county = (
        address.get("county")
        or address.get("state_district")
        or address.get("district")
        or ""
    )

    state = (
        address.get("state")
        or address.get("province")
        or address.get("region")
        or ""
    )

    country = address.get("country") or ""

    osm_class = str(item.get("class", "")).strip()
    osm_type = str(item.get("type", "")).strip()

    parts = [
        p for p in [
            city,
            county,
            state,
            country
        ]
        if p
    ]

    compact = ", ".join(parts)

    type_text = ""
    if osm_class or osm_type:
        type_text = f" [{osm_class}/{osm_type}]".replace("[/", "[").replace("/]", "]")

    if compact:
        return f"{compact}{type_text}"

    if display_name:
        return f"{display_name}{type_text}"

    return ""


def _suggest_osm_places_with_photon(place_query, limit=20):
    """Fallback place suggestions using Photon when Nominatim returns 429."""
    import requests

    raw = " ".join(str(place_query or "").replace("\n", " ").split()).strip()
    if not raw:
        return []

    response = requests.get(
        "https://photon.komoot.io/api/",
        params={
            "q": raw,
            "limit": int(limit),
            "lang": "en",
        },
        headers={
            "User-Agent": "Corridor-HIN-Streamlit-App/1.0",
            "Accept-Language": "en",
        },
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()

    suggestions = []
    seen = set()

    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []

        name = props.get("name") or props.get("city") or raw
        city = props.get("city") or props.get("town") or props.get("village") or name
        county = props.get("county") or props.get("district") or ""
        state = props.get("state") or ""
        country = props.get("country") or ""
        osm_value = props.get("osm_value") or "place"
        osm_key = props.get("osm_key") or ""

        parts = [p for p in [city, county, state, country] if p]
        label = ", ".join(parts)
        if osm_key or osm_value:
            label = f"{label} [{osm_key}/{osm_value}]".replace("[/", "[").replace("/]", "]")

        display_name_parts = [p for p in [name, county, state, country] if p]
        display_name = ", ".join(display_name_parts) or raw

        lon = coords[0] if len(coords) >= 2 else ""
        lat = coords[1] if len(coords) >= 2 else ""

        bbox = None
        extent = props.get("extent")
        if extent and len(extent) == 4:
            # Photon extent order: west, north, east, south.
            bbox = _normalize_bbox_dict(
                {
                    "west": extent[0],
                    "north": extent[1],
                    "east": extent[2],
                    "south": extent[3],
                }
            )

        if bbox is None:
            bbox = _bbox_from_point(lat, lon)

        key = (
            str(props.get("osm_type", "")),
            str(props.get("osm_id", "")),
            display_name.lower(),
        )
        if key in seen:
            continue
        seen.add(key)

        suggestions.append(
            {
                "display_name": display_name,
                "label": label or display_name,
                "osm_type": props.get("osm_type", ""),
                "osm_id": props.get("osm_id", ""),
                "class": osm_key,
                "type": osm_value,
                "lat": lat,
                "lon": lon,
                "bbox": bbox,
                "source": "Photon fallback",
            }
        )

        if len(suggestions) >= int(limit):
            break

    return suggestions[:int(limit)]


def suggest_osm_places(place_query, limit=20):
    """Return candidate place matches for a user-entered query.

    The first attempt uses one Nominatim request so the app can return many
    global matches without over-querying. If Nominatim returns HTTP 429, the
    function falls back to Photon so the dropdown can still work when the
    public Nominatim server temporarily blocks the app/IP.
    """
    if place_query is None or not str(place_query).strip():
        return []

    try:
        import requests
    except Exception as exc:
        raise ImportError(
            "The Python package 'requests' is required for OSM place search. "
            "Please add 'requests' to requirements.txt."
        ) from exc

    url = "https://nominatim.openstreetmap.org/search"

    headers = {
        "User-Agent": "Corridor-HIN-Streamlit-App/1.0",
        "Accept-Language": "en",
    }

    suggestions = []
    seen = set()
    errors = []
    saw_429 = False

    for params in _osm_suggestion_search_requests(
        place_query,
        limit=limit
    ):
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=25,
            )

            if response.status_code == 429:
                saw_429 = True
                errors.append("Nominatim HTTP 429 Too Many Requests")
                break

            if response.status_code != 200:
                errors.append(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                continue

            data = response.json()

        except Exception as exc:
            errors.append(str(exc))
            continue

        for item in data:
            display_name = str(item.get("display_name", "")).strip()

            if not display_name:
                continue

            bbox = _normalize_bbox_dict(item.get("boundingbox"))

            key = (
                str(item.get("osm_type", "")),
                str(item.get("osm_id", "")),
                display_name.lower(),
            )

            if key in seen:
                continue

            seen.add(key)

            label = _format_osm_suggestion_label(item)

            suggestions.append(
                {
                    "display_name": display_name,
                    "label": label or display_name,
                    "osm_type": item.get("osm_type", ""),
                    "osm_id": item.get("osm_id", ""),
                    "class": item.get("class", ""),
                    "type": item.get("type", ""),
                    "lat": item.get("lat", ""),
                    "lon": item.get("lon", ""),
                    "bbox": bbox,
                    "source": "Nominatim",
                }
            )

        if len(suggestions) >= int(limit):
            break

    if suggestions:
        return suggestions[:int(limit)]

    if saw_429:
        try:
            fallback_suggestions = _suggest_osm_places_with_photon(
                place_query,
                limit=limit,
            )
            if fallback_suggestions:
                return fallback_suggestions[:int(limit)]
        except Exception as exc:
            errors.append(f"Photon fallback failed: {exc}")

        raise ValueError(
            "Nominatim returned HTTP 429 Too Many Requests and the Photon fallback "
            "did not return usable suggestions. Please wait longer or try running "
            "locally instead of on Streamlit Cloud. Last error: "
            + (errors[-1] if errors else "unknown")
        )

    if errors:
        try:
            fallback_suggestions = _suggest_osm_places_with_photon(
                place_query,
                limit=limit,
            )
            if fallback_suggestions:
                return fallback_suggestions[:int(limit)]
        except Exception as exc:
            errors.append(f"Photon fallback failed: {exc}")

        raise ValueError(
            "OSM place search failed. Last error: "
            + errors[-1]
        )

    return []


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
