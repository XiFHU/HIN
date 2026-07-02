"""Crash field mapping and normalization utilities.

This module keeps uploaded/FARS/local crash datasets flexible.  It does not
assume one fixed schema.  Instead it auto-suggests important fields, lets the
user confirm/change them, and writes canonical dashboard columns that the rest
of the app can use consistently.
"""

import re
from datetime import datetime

import pandas as pd


CANONICAL_FIELDS = {
    "crash_id": "Crash ID / case ID",
    "crash_date": "Crash date / timestamp",
    "crash_year": "Crash year",
    "crash_month": "Crash month",
    "crash_type": "Crash type / manner of collision",
    "severity": "Severity / KABCO text",
    "fatalities": "Fatalities person count",
    "serious_injuries": "Serious injuries person count",
    "minor_injuries": "Minor injuries / B person count",
    "possible_injuries": "Possible injuries / C person count",
    "no_injury": "No injury / uninjured / PDO count",
    "mode": "Mode / vehicle type / person type",
}

FIELD_ALIASES = {
    "crash_id": [
        "sourcecrashid", "crashid", "crash_id", "caseid", "case_id", "accidentid",
        "accident_id", "st_case", "stcase", "objectid", "case_number", "casenumber",
        "reportnumber", "report_number", "id",
    ],
    "crash_date": [
        "crashdate", "crash_date", "date", "datetime", "crashdatetime", "crash_time",
        "accidentdate", "accident_date", "incidentdate", "collisndate", "date_time",
    ],
    "crash_year": [
        "year", "crashyear", "crash_year", "u_year", "caseyear", "accidentyear",
        "accident_year", "yr",
    ],
    "crash_month": [
        "month", "crashmonth", "crash_month", "u_month", "monthname", "month_name",
        "accidentmonth", "accident_month",
    ],
    "crash_type": [
        "crashtype", "crash_type", "collisiontype", "collision_type", "manner", "mannerofcollision",
        "manner_of_collision", "man_coll", "mancoll", "man_collname", "man_coll_name",
        "firstharmfulevent", "first_harmful_event", "harmful_event", "eventtype",
        "accidenttype", "type", "collision", "manner_coll", "manner_coll_name",
    ],
    "severity": [
        "kabco", "k_a_b_c_o", "severity", "crashseverity", "crash_severity", "injuryseverity",
        "injury_severity", "maxseverity", "max_severity", "injuryclass", "injury_class",
        "severityname", "severity_name",
    ],
    "fatalities": [
        "fatalities", "fatality", "fatals", "fatal", "fatalcount", "fatal_count", "k", "killed",
        "persons_killed", "numberofpersonskilled", "fatal_injuries",
    ],
    "serious_injuries": [
        "seriousinjuries", "serious_injuries", "seriousinjury", "serious_injury", "levelainjuries",
        "level_a_injuries", "ainjuries", "a_injuries", "incapacitating", "suspectedseriousinjuries",
        "suspected_serious_injuries", "injuriesa", "injury_a", "a",
    ],
    "minor_injuries": [
        "levelbinjuries", "level_b_injuries", "binjuries", "b_injuries", "nonincapacitating",
        "non_incapacitating", "minorinjuries", "minor_injuries", "suspectedminorinjuries",
        "suspected_minor_injuries", "injuriesb", "injury_b", "b",
    ],
    "possible_injuries": [
        "levelcinjuries", "level_c_injuries", "cinjuries", "c_injuries", "possibleinjuries",
        "possible_injuries", "complaintofinjury", "complaint_of_injury", "injuriesc", "injury_c", "c",
    ],
    "no_injury": [
        "uninjured", "noinjury", "no_injury", "pdo", "propertydamageonly", "property_damage_only",
        "oinjuries", "o_injuries", "notinjured", "not_injured", "o",
    ],
    "mode": [
        "mode", "travelmode", "travel_mode", "vehicletype", "vehicle_type", "veh_type",
        "bodytype", "body_type", "persontype", "person_type", "roaduser", "road_user",
    ],
}

MONTH_LOOKUP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _score_column(col, aliases):
    n = _norm(col)
    best = 0
    for alias in aliases:
        a = _norm(alias)
        if not a:
            continue
        # Single-letter aliases such as K/A/B/C/O should only match exact
        # column names.  Otherwise a severity field named KABCO can be
        # incorrectly selected as a B/C/O person-count field.
        if len(a) == 1:
            if n == a:
                best = max(best, 100)
            continue
        if n == a:
            best = max(best, 100)
        elif a in n:
            best = max(best, 85)
        elif n and n in a and len(n) > 2:
            best = max(best, 70)
    return best


def _first_existing_column(df, candidates):
    if df is None:
        return None
    lower_map = {str(c).lower().replace("_", "").replace(" ", ""): c for c in df.columns}
    for candidate in candidates:
        key = str(candidate).lower().replace("_", "").replace(" ", "")
        if key in lower_map:
            return lower_map[key]
    for c in df.columns:
        low = str(c).lower().replace("_", "").replace(" ", "")
        for candidate in candidates:
            key = str(candidate).lower().replace("_", "").replace(" ", "")
            if key and key in low:
                return c
    return None


def is_fars_fatal_only_dataset(df):
    """Return True only for confirmed FARS Accident fatal-crash data.

    Local crash datasets can contain columns such as SourceCrashID or
    Fatalities, so those fields alone must not force every crash to K.
    """
    if df is None or getattr(df, "empty", True):
        return False

    if "CrashSource" in df.columns:
        try:
            if df["CrashSource"].dropna().astype(str).str.upper().eq("FARS").any():
                return True
        except Exception:
            pass

    cols = {str(c).lower() for c in df.columns}

    # ST_CASE is specific to FARS/NHTSA. SourceCrashID is not enough because
    # uploaded local datasets may also use that column name.
    fars_specific_cols = {
        "st_case",
        "ve_total",
        "veh_no",
        "man_collname",
        "harm_evname",
        "func_sysname",
        "route_name",
        "rur_urbname",
    }

    return bool(cols.intersection(fars_specific_cols)) and (
        "fatals" in cols
        or "fatalities" in cols
    )


def _apply_fars_mapping_defaults(df, mapping):
    mapping = {key: mapping.get(key, "") for key in CANONICAL_FIELDS}
    if not is_fars_fatal_only_dataset(df):
        return mapping
    mapping["crash_id"] = _first_existing_column(df, ["SourceCrashID", "ST_CASE", "CrashID", "Case_ID"]) or mapping.get("crash_id", "")
    mapping["crash_year"] = _first_existing_column(df, ["Year", "YEAR", "CaseYear"]) or mapping.get("crash_year", "")
    mapping["crash_month"] = _first_existing_column(df, ["MonthName", "MONTHNAME", "Month", "MONTH"]) or mapping.get("crash_month", "")
    mapping["crash_type"] = _first_existing_column(df, ["man_collname", "MAN_COLLNAME", "Crash_Type", "CrashType", "Manner"]) or mapping.get("crash_type", "")
    mapping["severity"] = _first_existing_column(df, ["KABCO", "CrashSeverity"]) or mapping.get("severity", "")
    mapping["fatalities"] = _first_existing_column(df, ["Fatalities", "FATALITIES", "Fatals", "FATALS"]) or mapping.get("fatalities", "")
    # FARS Accident is fatal-only.  Do not auto-map these to generic injury
    # fields because they are not local crash-level A/B/C/O counts.
    mapping["serious_injuries"] = ""
    mapping["minor_injuries"] = ""
    mapping["possible_injuries"] = ""
    mapping["no_injury"] = ""
    mapping["mode"] = _first_existing_column(df, ["VehType_1", "BodyType", "PersonType", "Vehicle_Type"]) or mapping.get("mode", "")
    return mapping


def detect_field_mapping(df):
    """Return a best-effort mapping from semantic field names to columns."""
    mapping = {key: "" for key in CANONICAL_FIELDS}
    if df is None:
        return mapping
    columns = [c for c in df.columns if str(c).lower() != "geometry"]
    for field, aliases in FIELD_ALIASES.items():
        scored = [(c, _score_column(c, aliases)) for c in columns]
        scored = sorted(scored, key=lambda x: x[1], reverse=True)
        if scored and scored[0][1] >= 70:
            mapping[field] = scored[0][0]

    # Value-based fallback for crash type: find a text column containing collision-type words.
    if not mapping.get("crash_type"):
        type_words = [
            "rear", "front", "broadside", "sideswipe", "angle", "head on", "head-on",
            "pedestrian", "bicycle", "overturn", "approach", "fixed object", "parked",
        ]
        best_col, best_hits = "", 0
        for c in columns:
            try:
                s = df[c].dropna().astype(str).head(1000).str.lower()
                if s.empty:
                    continue
                hits = sum(int(s.str.contains(w, regex=False).any()) for w in type_words)
                nunique = df[c].nunique(dropna=True)
                if hits > best_hits and 1 < nunique < max(200, len(df) * 0.6):
                    best_col, best_hits = c, hits
            except Exception:
                continue
        if best_hits >= 2:
            mapping["crash_type"] = best_col

    mapping = _apply_fars_mapping_defaults(df, mapping)

    return mapping


def normalize_kabco_value(value):
    """Normalize common crash severity labels to K/A/B/C/O."""
    if value is None:
        return "Unknown"
    text = str(value).strip()
    if not text:
        return "Unknown"
    upper = text.upper().strip()
    if upper in {"K", "A", "B", "C", "O"}:
        return upper
    if upper in {"PDO", "N", "NO INJURY"}:
        return "O"
    s = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    # Order matters.  Check B non-incapacitating before A incapacitating because
    # the word "incapacitating" is contained inside "non-incapacitating".
    if "fatal" in s or "killed" in s or "death" in s or re.search(r"\bk\b", s):
        return "K"
    if "non incapacitating" in s or "nonincapacitating" in s or "level b" in s or re.search(r"\bb\b", s) or "minor" in s:
        return "B"
    if "incapacitating" in s or "serious" in s or "level a" in s or re.search(r"\ba\b", s):
        return "A"
    if "possible" in s or "complaint" in s or "level c" in s or re.search(r"\bc\b", s):
        return "C"
    if "no injury" in s or "uninjured" in s or "not injured" in s or "property damage" in s or "pdo" in s or re.search(r"\bo\b", s):
        return "O"
    return text


def parse_month_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return int(value.month)
    text = str(value).strip()
    if not text:
        return None
    low = text.lower()[:9]
    if low in MONTH_LOOKUP:
        return MONTH_LOOKUP[low]
    if low[:3] in MONTH_LOOKUP:
        return MONTH_LOOKUP[low[:3]]
    num = pd.to_numeric(text, errors="coerce")
    if pd.notna(num) and 1 <= int(num) <= 12:
        return int(num)
    dt = pd.to_datetime(text, errors="coerce")
    if pd.notna(dt):
        return int(dt.month)
    return None


def _as_numeric_series(df, col):
    if col and col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0)
    return pd.Series([0] * len(df), index=df.index, dtype="float64")


def apply_field_mapping(df, mapping):
    """Add canonical columns used by dashboard/report logic."""
    if df is None:
        return df
    out = df.copy()
    mapping = mapping or {}

    def col(name):
        c = mapping.get(name, "")
        return c if c in out.columns else None

    id_col = col("crash_id")
    if id_col:
        out["DashboardCrashID"] = out[id_col].fillna("").astype(str)
        if "SourceCrashID" not in out.columns:
            out["SourceCrashID"] = out["DashboardCrashID"]

    date_col = col("crash_date")
    if date_col:
        out["DashboardCrashDate"] = pd.to_datetime(out[date_col], errors="coerce")

    year_col = col("crash_year")
    if year_col:
        out["DashboardCrashYear"] = pd.to_numeric(out[year_col], errors="coerce")
    elif "DashboardCrashDate" in out.columns:
        out["DashboardCrashYear"] = out["DashboardCrashDate"].dt.year

    month_col = col("crash_month")
    if month_col:
        out["DashboardCrashMonth"] = out[month_col].map(parse_month_value)
    elif "DashboardCrashDate" in out.columns:
        out["DashboardCrashMonth"] = out["DashboardCrashDate"].dt.month

    type_col = col("crash_type")
    if type_col:
        out["DashboardCrashType"] = out[type_col].fillna("Unknown").astype(str)

    sev_col = col("severity")
    if sev_col:
        # Keep the user-facing severity labels exactly as they appear in the
        # mapped severity column.  Filters, legends, and color-by-severity
        # controls should show agency labels such as "Fatal (K)" or
        # "Evident Incapacitating (A)".  A separate normalized KABCO code is
        # still created for calculations such as KSI, EPDO, and KABCO summaries.
        out["DashboardSeverityLabel"] = (
            out[sev_col]
            .fillna("Unknown")
            .astype(str)
            .str.strip()
            .replace({"": "Unknown"})
        )
        out["CrashSeverityLabel"] = out["DashboardSeverityLabel"]
        out["DashboardKABCO"] = out[sev_col].map(normalize_kabco_value)
    else:
        # Derive one representative severity per crash from person-count fields.
        k = _as_numeric_series(out, col("fatalities"))
        a = _as_numeric_series(out, col("serious_injuries"))
        b = _as_numeric_series(out, col("minor_injuries"))
        c = _as_numeric_series(out, col("possible_injuries"))
        o = _as_numeric_series(out, col("no_injury"))
        out["DashboardKABCO"] = "O"
        out.loc[c > 0, "DashboardKABCO"] = "C"
        out.loc[b > 0, "DashboardKABCO"] = "B"
        out.loc[a > 0, "DashboardKABCO"] = "A"
        out.loc[k > 0, "DashboardKABCO"] = "K"
        out["DashboardSeverityLabel"] = out["DashboardKABCO"]
        out["CrashSeverityLabel"] = out["DashboardSeverityLabel"]

    # Keep KABCO as a normalized calculation field.  Do not use it for the
    # user-facing severity filter/legend when DashboardSeverityLabel exists.
    if "DashboardKABCO" in out.columns:
        out["KABCO"] = out["DashboardKABCO"]

    fatal_col = col("fatalities")
    serious_col = col("serious_injuries")
    minor_col = col("minor_injuries")
    possible_col = col("possible_injuries")
    noinj_col = col("no_injury")
    out["DashboardFatalities"] = _as_numeric_series(out, fatal_col)
    out["DashboardSeriousInjuries"] = _as_numeric_series(out, serious_col)
    out["DashboardMinorInjuries"] = _as_numeric_series(out, minor_col)
    out["DashboardPossibleInjuries"] = _as_numeric_series(out, possible_col)
    out["DashboardNoInjury"] = _as_numeric_series(out, noinj_col)
    if is_fars_fatal_only_dataset(out):
        out["DashboardKABCO"] = "K"
        out["DashboardSeverityLabel"] = "Fatal (K)"
        out["CrashSeverityLabel"] = out["DashboardSeverityLabel"]
        out["KABCO"] = "K"
        if "DashboardFatalities" not in out.columns or pd.to_numeric(out["DashboardFatalities"], errors="coerce").fillna(0).sum() == 0:
            out["DashboardFatalities"] = 1
        out["DashboardSeriousInjuries"] = 0
        out["DashboardMinorInjuries"] = 0
        out["DashboardPossibleInjuries"] = 0
        out["DashboardNoInjury"] = 0
        out["DashboardFatalOnlySource"] = True

    out["DashboardFatalCrashFlag"] = (out["DashboardFatalities"] > 0) | (out.get("DashboardKABCO", "") == "K")
    out["DashboardSeriousCrashFlag"] = (out["DashboardSeriousInjuries"] > 0) | (out.get("DashboardKABCO", "") == "A")

    mode_col = col("mode")
    if mode_col:
        out["DashboardMode"] = out[mode_col].fillna("Unknown").astype(str)

    return out


def render_field_mapping_ui(st, df, key_prefix="crash_field_mapping"):
    """Render mapping UI and return the selected mapping."""
    if df is None:
        return {}
    detected = detect_field_mapping(df)
    state_key = f"{key_prefix}_values"
    if state_key not in st.session_state:
        st.session_state[state_key] = detected
    elif is_fars_fatal_only_dataset(df):
        # Clean old session mappings from earlier app versions where KABCO could
        # have been incorrectly selected as B/C/O person-count columns.
        st.session_state[state_key] = _apply_fars_mapping_defaults(df, st.session_state[state_key])

    columns = [""] + [c for c in df.columns if str(c).lower() != "geometry"]
    with st.expander("Crash field mapping", expanded=False):
        st.caption(
            "The app auto-detects common crash fields, but different agencies use different column names. "
            "Confirm or change these fields once, then the same mapping is used by filters, dashboards, and reports."
        )
        c1, c2 = st.columns(2)
        new_mapping = {}
        items = list(CANONICAL_FIELDS.items())
        for i, (field, label) in enumerate(items):
            box = c1 if i % 2 == 0 else c2
            current = st.session_state[state_key].get(field, detected.get(field, ""))
            index = columns.index(current) if current in columns else 0
            with box:
                new_mapping[field] = st.selectbox(
                    label,
                    columns,
                    index=index,
                    key=f"{key_prefix}_{field}",
                )
        if st.button("Use auto-detected fields", key=f"{key_prefix}_reset"):
            st.session_state[state_key] = detected
            st.rerun()
        st.info(
            "Recommended minimum mapping: Crash ID, Date or Year, Crash Type, and either Severity/KABCO or person-count injury fields."
        )
    st.session_state[state_key] = new_mapping
    st.session_state["crash_field_mapping"] = new_mapping
    return new_mapping
