"""FARS crash-data download helpers.

This module uses the official NHTSA CrashAPI so users can choose a
"no upload" fatal-crash data source in the Streamlit workflow.
"""

import json
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import geopandas as gpd
import pandas as pd

try:
    import requests
except Exception:  # pragma: no cover - urllib fallback is used when requests is unavailable.
    requests = None

from modules.crashes import detect_lat_lon


FARS_STATE_CODES = {
    "Alabama": 1,
    "Alaska": 2,
    "Arizona": 4,
    "Arkansas": 5,
    "California": 6,
    "Colorado": 8,
    "Connecticut": 9,
    "Delaware": 10,
    "District of Columbia": 11,
    "Florida": 12,
    "Georgia": 13,
    "Hawaii": 15,
    "Idaho": 16,
    "Illinois": 17,
    "Indiana": 18,
    "Iowa": 19,
    "Kansas": 20,
    "Kentucky": 21,
    "Louisiana": 22,
    "Maine": 23,
    "Maryland": 24,
    "Massachusetts": 25,
    "Michigan": 26,
    "Minnesota": 27,
    "Mississippi": 28,
    "Missouri": 29,
    "Montana": 30,
    "Nebraska": 31,
    "Nevada": 32,
    "New Hampshire": 33,
    "New Jersey": 34,
    "New Mexico": 35,
    "New York": 36,
    "North Carolina": 37,
    "North Dakota": 38,
    "Ohio": 39,
    "Oklahoma": 40,
    "Oregon": 41,
    "Pennsylvania": 42,
    "Rhode Island": 44,
    "South Carolina": 45,
    "South Dakota": 46,
    "Tennessee": 47,
    "Texas": 48,
    "Utah": 49,
    "Vermont": 50,
    "Virginia": 51,
    "Washington": 53,
    "West Virginia": 54,
    "Wisconsin": 55,
    "Wyoming": 56,
    "Puerto Rico": 72,
}


FARS_API_BASE = "https://crashviewer.nhtsa.dot.gov/crashviewer/crashapi"


def detect_county_fips_from_boundary(boundary_gdf, timeout=30):
    """Detect state/county FIPS from a study-area boundary.

    Uses the public U.S. Census geocoder coordinate endpoint at the
    representative point of the selected boundary. The returned county code is
    the three-digit county FIPS within the state, which is what the NHTSA
    GetCrashesByLocation endpoint expects.
    """
    if boundary_gdf is None or getattr(boundary_gdf, "empty", True):
        raise ValueError(
            "No study-area boundary is available. Select or download a road "
            "study area before auto-detecting the FARS county code."
        )

    boundary = boundary_gdf.copy()
    if boundary.crs is None:
        boundary = boundary.set_crs(4326, allow_override=True)
    elif str(boundary.crs).upper() not in ["EPSG:4326", "WGS84"]:
        boundary = boundary.to_crs(4326)

    geom = boundary.geometry.unary_union
    if geom is None or geom.is_empty:
        raise ValueError("The selected boundary geometry is empty.")

    point = geom.representative_point()
    lon = float(point.x)
    lat = float(point.y)

    params = {
        "x": lon,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Counties",
        "format": "json",
    }

    url = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates?" + urlencode(params)

    request = Request(
        url,
        headers={
            "User-Agent": "HIN-Analysis-Tool/1.0",
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    geographies = (
        payload
        .get("result", {})
        .get("geographies", {})
    )

    counties = geographies.get("Counties", [])

    if not counties:
        raise ValueError(
            "The Census geocoder did not return a county for the selected boundary."
        )

    county = counties[0]
    geoid = str(county.get("GEOID", "")).strip()
    county_name = str(county.get("NAME", "")).strip()

    if len(geoid) < 5 or not geoid.isdigit():
        raise ValueError(
            "The Census geocoder returned a county, but not a usable GEOID."
        )

    return {
        "state_fips": int(geoid[:2]),
        "county_fips": int(geoid[-3:]),
        "county_fips_text": str(int(geoid[-3:])),
        "full_county_geoid": geoid,
        "county_name": county_name,
        "longitude": lon,
        "latitude": lat,
    }



def build_fars_location_url(
    state_code,
    from_year,
    to_year,
    county_code,
    output_format="csv",
):
    """Build the documented NHTSA GetCrashesByLocation URL.

    This is state/county driven, so it works for every FARS state supported
    by the NHTSA endpoint, not only Colorado.
    """
    params = {
        "fromCaseYear": int(from_year),
        "toCaseYear": int(to_year),
        "state": int(state_code),
        "county": int(str(county_code).strip()),
        "format": output_format,
    }
    endpoint = f"{FARS_API_BASE}/crashes/GetCrashesByLocation"
    return f"{endpoint}?{urlencode(params)}"




def build_fars_accident_data_url(
    state_code,
    from_year,
    to_year,
    output_format="csv",
):
    """Build the documented NHTSA FARSData Accident dataset URL.

    This endpoint downloads the statewide Accident table for the selected
    years. It does not accept county as a URL parameter, so the app filters to
    the detected/manual county after the user uploads the downloaded CSV.
    """
    params = {
        "dataset": "Accident",
        "FromYear": int(from_year),
        "ToYear": int(to_year),
        "State": int(state_code),
        "format": output_format,
    }
    endpoint = f"{FARS_API_BASE}/FARSData/GetFARSData"
    return f"{endpoint}?{urlencode(params)}"


def parse_fars_accident_csv(
    fars_csv_file,
    county_code=None,
):
    """Parse a downloaded NHTSA FARSData Accident CSV into crash points.

    The FARSData endpoint returns statewide rows. If county_code is supplied,
    records are filtered to that county code within the selected state.
    """
    df = pd.read_csv(fars_csv_file)

    if df.empty:
        return gpd.GeoDataFrame(
            columns=[
                "SourceCrashID",
                "CrashID",
                "KABCO",
                "CrashSeverity",
                "CrashSource",
                "geometry",
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )

    county_col = _first_existing_column(
        df,
        ["COUNTY", "county", "County", "CountyCode", "COUNTYCODE"]
    )

    if county_code is not None and str(county_code).strip() and county_col is not None:
        target_county = int(str(county_code).strip())
        df[county_col] = pd.to_numeric(df[county_col], errors="coerce")
        df = df[df[county_col] == target_county].copy()

    df = _standardize_fars_columns(df)

    lat_col, lon_col = detect_lat_lon(df)

    if lat_col is None or lon_col is None:
        raise ValueError(
            "The uploaded FARS Accident CSV did not include usable "
            "latitude/longitude fields. Make sure the CSV is the Accident "
            "dataset from the FARSData endpoint."
        )

    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")

    df = df[
        df[lat_col].between(-90, 90)
        & df[lon_col].between(-180, 180)
    ].copy()

    df = df[
        (df[lat_col].abs() > 0.000001)
        & (df[lon_col].abs() > 0.000001)
        & (df[lon_col] < 0)
    ].copy()

    if df.empty:
        return gpd.GeoDataFrame(
            df,
            geometry=[],
            crs="EPSG:4326",
        )

    crashes = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
        crs="EPSG:4326",
    )

    crashes = crashes.reset_index(drop=True)
    crashes["CrashID"] = (crashes.index + 1).astype(int)

    return crashes

def _read_url_bytes(url, headers, timeout):
    """Read URL bytes with requests first, then urllib fallback."""
    if requests is not None:
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
            )
            if response.status_code == 200:
                return response.content
            raise ValueError(
                f"HTTP {response.status_code}: {response.reason}"
            )
        except Exception as exc:
            requests_error = str(exc)
    else:
        requests_error = "requests package is not installed"

    try:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise ValueError(
            f"requests failed ({requests_error}); urllib HTTP {exc.code}: {exc.reason}"
        ) from exc
    except URLError as exc:
        raise ValueError(
            f"requests failed ({requests_error}); urllib URL error: {exc.reason}"
        ) from exc


def _download_location_dataframe(params, timeout):
    """Download GetCrashesByLocation as a DataFrame.

    The documented URL supports CSV and JSON. Use CSV first because the
    location CSV is flat and includes latitude/longitud fields directly. JSON
    remains a fallback for environments where CSV is unavailable.
    """

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/csv,application/json,*/*",
        "Referer": "https://crashviewer.nhtsa.dot.gov/crashviewer/crashapi",
    }

    errors = []

    for fmt in ["csv", "json"]:
        url = build_fars_location_url(
            state_code=params["state"],
            from_year=params["fromCaseYear"],
            to_year=params["toCaseYear"],
            county_code=params["county"],
            output_format=fmt,
        )

        try:
            raw = _read_url_bytes(url, headers=headers, timeout=timeout)
        except Exception as exc:
            errors.append(f"{fmt.upper()} request failed: {exc}")
            continue

        if fmt == "csv":
            try:
                return pd.read_csv(BytesIO(raw))
            except Exception as exc:
                errors.append(f"CSV parse error: {exc}")
                continue

        try:
            payload = json.loads(raw.decode("utf-8-sig"))
            records = _extract_records(payload)
            return pd.DataFrame(records)
        except Exception as exc:
            errors.append(f"JSON parse error: {exc}")
            continue

    csv_url = build_fars_location_url(
        state_code=params["state"],
        from_year=params["fromCaseYear"],
        to_year=params["toCaseYear"],
        county_code=params["county"],
        output_format="csv",
    )
    raise ValueError(
        "NHTSA FARS CrashAPI request failed from inside the app. "
        "The same URL may still work in a browser. Open this CSV URL in your "
        "browser, download the CSV, and upload it as a crash file if direct app "
        "download is blocked: "
        + csv_url
        + " Details: "
        + " | ".join(errors)
    )

def _extract_records(value):
    """Recursively extract list-of-dict records from CrashAPI JSON."""
    if value is None:
        return []

    if isinstance(value, dict):
        for key in ["Results", "results", "Data", "data", "records"]:
            if key in value:
                records = _extract_records(value[key])
                if records:
                    return records

        # Sometimes wrapper dictionaries contain one nested list under an
        # unexpected key. Return the first non-empty record list we find.
        for child in value.values():
            records = _extract_records(child)
            if records:
                return records

        return []

    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            return value

        records = []
        for item in value:
            records.extend(_extract_records(item))
        return records

    return []


def _first_existing_column(df, candidates):
    normalized = {
        str(c).lower().replace(" ", "_"): c
        for c in df.columns
    }

    for candidate in candidates:
        key = str(candidate).lower().replace(" ", "_")
        if key in normalized:
            return normalized[key]

    return None


def _standardize_fars_columns(df):
    df = df.copy()

    year_col = _first_existing_column(
        df,
        ["Year", "YEAR", "CaseYear", "CASEYEAR", "case_year", "C_YEAR"]
    )

    if year_col is not None:
        df["Year"] = pd.to_numeric(df[year_col], errors="coerce")

    fatal_col = _first_existing_column(
        df,
        ["Fatalities", "FATALITIES", "Fatals", "FATALS", "NumberOfFatalities"]
    )

    if fatal_col is not None:
        df["Fatalities"] = pd.to_numeric(df[fatal_col], errors="coerce").fillna(1)
    else:
        df["Fatalities"] = 1

    case_col = _first_existing_column(
        df,
        ["ST_CASE", "StateCase", "state_case", "CaseNumber", "CASE_NUMBER", "case_id"]
    )

    if case_col is not None:
        df["SourceCrashID"] = df[case_col].fillna("").astype(str).str.strip()
    else:
        df["SourceCrashID"] = [f"FARS_{i + 1}" for i in range(len(df))]

    df["KABCO"] = "K"
    df["CrashSeverity"] = "Fatality (K)"
    df["CrashSource"] = "FARS"

    return df


def load_fars_crashes_by_location(
    state_code,
    from_year,
    to_year,
    county_code=None,
    timeout=90,
):
    """Load FARS fatal crashes from the official NHTSA CrashAPI.

    Parameters
    ----------
    state_code : int or str
        FARS/NHTSA state code. These match state FIPS codes for states.
    from_year, to_year : int
        Inclusive FARS case-year range.
    county_code : int or str, optional
        County FIPS code within the selected state. Leave blank to download
        all counties in the state and then spatially filter inside the app.
    timeout : int
        Request timeout in seconds.
    """
    params = {
        "fromCaseYear": int(from_year),
        "toCaseYear": int(to_year),
        "state": int(state_code),
    }

    if county_code is None or not str(county_code).strip():
        raise ValueError(
            "County FIPS code is required for the NHTSA "
            "GetCrashesByLocation endpoint. Enter the county code "
            "within the selected state, not the full five-digit FIPS code."
        )

    params["county"] = int(str(county_code).strip())

    df = _download_location_dataframe(params, timeout=timeout)

    if df.empty:
        return gpd.GeoDataFrame(
            columns=[
                "SourceCrashID",
                "CrashID",
                "KABCO",
                "CrashSeverity",
                "CrashSource",
                "geometry",
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )

    df = _standardize_fars_columns(df)

    lat_col, lon_col = detect_lat_lon(df)

    if lat_col is None or lon_col is None:
        raise ValueError(
            "FARS response did not include usable latitude/longitude fields. "
            "Try a different year range or use an uploaded crash file."
        )

    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")

    df = df[
        df[lat_col].between(-90, 90)
        & df[lon_col].between(-180, 180)
    ].copy()

    # FARS can use placeholder values for unknown coordinates. Remove common
    # invalid placeholders and keep only likely western-hemisphere US points.
    df = df[
        (df[lat_col].abs() > 0.000001)
        & (df[lon_col].abs() > 0.000001)
        & (df[lon_col] < 0)
    ].copy()

    if df.empty:
        return gpd.GeoDataFrame(
            df,
            geometry=[],
            crs="EPSG:4326",
        )

    crashes = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
        crs="EPSG:4326",
    )

    crashes = crashes.reset_index(drop=True)
    crashes["CrashID"] = (crashes.index + 1).astype(int)

    return crashes
