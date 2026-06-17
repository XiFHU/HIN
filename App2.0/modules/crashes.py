# modules/crashes.py

import geopandas as gpd


LAT_KEYWORDS = [
    "lat",
    "latitude",
    "y",
    "y_coord",
    "ycoordinate",
    "gps_lat",
    "crash_lat",
    "crash_latitude"
]

LON_KEYWORDS = [
    "lon",
    "long",
    "lng",
    "longitude",
    "x",
    "x_coord",
    "xcoordinate",
    "gps_lon",
    "gps_lng",
    "crash_lon",
    "crash_longitude"
]


def normalize_col_name(name):
    return (
        str(name)
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )


def detect_lat_lon(df):
    lat_col = None
    lon_col = None

    normalized = {
        c: normalize_col_name(c)
        for c in df.columns
    }

    for c, n in normalized.items():
        if n in [normalize_col_name(x) for x in LAT_KEYWORDS]:
            lat_col = c
            break

    for c, n in normalized.items():
        if n in [normalize_col_name(x) for x in LON_KEYWORDS]:
            lon_col = c
            break

    if lat_col is None:
        for c, n in normalized.items():
            if "lat" in n:
                lat_col = c
                break

    if lon_col is None:
        for c, n in normalized.items():
            if "lon" in n or "lng" in n or "long" in n:
                lon_col = c
                break

    return lat_col, lon_col


def crash_points(df):
    lat_col, lon_col = detect_lat_lon(df)

    if lat_col is None or lon_col is None:
        raise ValueError(
            "Latitude/Longitude columns not found. "
            "Please make sure crash data has latitude and longitude fields."
        )

    df = df.copy()

    df[lat_col] = df[lat_col].astype(float)
    df[lon_col] = df[lon_col].astype(float)

    crashes = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(
            df[lon_col],
            df[lat_col]
        ),
        crs="EPSG:4326"
    )

    crashes = crashes[
        crashes.geometry.notna()
    ].copy()

    crashes = crashes[
        ~crashes.geometry.is_empty
    ].copy()

    crashes = crashes.reset_index(
        drop=True
    )

    possible_id_fields = [
        "Case_ID",
        "CASE_ID",
        "case_id",
        "CaseID",
        "caseid",
        "CrashID",
        "CRASH_ID",
        "Crash_ID",
        "crash_id",
        "ACCIDENT_ID",
        "accident_id",
        "CaseNumber",
        "CASE_NUMBER",
        "case_number",
        "OBJECTID",
        "objectid"
    ]
    source_id = None

    for field in possible_id_fields:

        if field in crashes.columns:
            source_id = field
            break

    if source_id is not None:

        crashes["SourceCrashID"] = (
            crashes[source_id]
            .fillna("")
            .astype(str)
            .str.strip()
        )
    else:

        crashes["SourceCrashID"] = (
            crashes.index + 1
        ).astype(str)

    crashes["CrashID"] = (
        crashes.index + 1
    )

    return crashes
