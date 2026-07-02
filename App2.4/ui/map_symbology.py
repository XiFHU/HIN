"""Reusable map symbology controls and color helpers."""

import html

import pandas as pd
import streamlit as st


RAMP_COLORS = [
    "green",
    "#7fbf3f",
    "#c7e600",
    "yellow",
    "orange",
    "#ff6600",
    "red",
    "#b30000",
    "#800000",
]

# Use the full green-to-red range for classed maps. The previous version
# sliced the first N colors from RAMP_COLORS, so a 5-class map could stop at
# orange and never reach red.
CLASS_RAMP_COLORS = [
    "green",
    "#7fbf3f",
    "yellow",
    "orange",
    "red",
]

CATEGORY_COLORS = [
    "#e41a1c",
    "#377eb8",
    "#4daf4a",
    "#984ea3",
    "#ff7f00",
    "#ffff33",
    "#a65628",
    "#f781bf",
    "#999999",
    "#66c2a5",
    "#fc8d62",
    "#8da0cb",
    "#e78ac3",
    "#a6d854",
    "#ffd92f",
]

NUMERIC_METHODS = [
    "Continuous gradient",
    "Capped gradient",
    "Equal interval",
    "Quantile",
    "Natural breaks",
    "Manual breaks",
]


def _fmt(value):
    try:
        value = float(value)
    except Exception:
        return str(value)
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _clean_values(values):
    vals = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    vals = vals.replace([float("inf"), -float("inf")], pd.NA).dropna()
    return vals.astype(float)


def _unique_sorted_breaks(breaks):
    clean = []
    for value in breaks:
        try:
            value = float(value)
        except Exception:
            continue
        if not clean or value > clean[-1]:
            clean.append(value)
    return clean


def _jenks_breaks(values, n_classes):
    """Small Jenks natural breaks implementation with quantile fallback."""
    vals = sorted(float(v) for v in values if pd.notna(v))
    if not vals:
        return [0.0, 1.0]

    unique_vals = sorted(set(vals))
    if len(unique_vals) <= n_classes:
        return _unique_sorted_breaks([unique_vals[0]] + unique_vals[1:] + [unique_vals[-1]])

    n_data = len(vals)
    n_classes = max(1, min(int(n_classes), n_data))
    lower = [[0] * (n_classes + 1) for _ in range(n_data + 1)]
    var = [[0.0] * (n_classes + 1) for _ in range(n_data + 1)]

    for i in range(1, n_classes + 1):
        lower[1][i] = 1
        var[1][i] = 0.0
        for j in range(2, n_data + 1):
            var[j][i] = float("inf")

    for l in range(2, n_data + 1):
        s1 = s2 = w = 0.0
        for m in range(1, l + 1):
            i3 = l - m + 1
            val = vals[i3 - 1]
            s2 += val * val
            s1 += val
            w += 1
            variance = s2 - (s1 * s1) / w
            i4 = i3 - 1
            if i4 != 0:
                for j in range(2, n_classes + 1):
                    if var[l][j] >= variance + var[i4][j - 1]:
                        lower[l][j] = i3
                        var[l][j] = variance + var[i4][j - 1]
        lower[l][1] = 1
        var[l][1] = variance

    k = n_data
    breaks = [0.0] * (n_classes + 1)
    breaks[n_classes] = vals[-1]
    breaks[0] = vals[0]
    count = n_classes
    while count >= 2:
        idx = int(lower[k][count] - 2)
        breaks[count - 1] = vals[max(0, idx)]
        k = int(lower[k][count] - 1)
        count -= 1

    return _unique_sorted_breaks(breaks)


def compute_breaks(values, method, num_classes=5, cap_percentile=95, manual_breaks_text=""):
    vals = _clean_values(values)
    if vals.empty:
        return [0.0, 1.0], 0.0, 1.0

    actual_min = float(vals.min())
    actual_max = float(vals.max())
    vmin = 0.0 if actual_min >= 0 else actual_min
    if actual_max <= vmin:
        actual_max = vmin + 1.0

    num_classes = max(3, min(int(num_classes), 9))

    if method == "Capped gradient":
        # For crash density/HIN data, many features can be exactly zero.
        # If we calculate P95 using all values, the cap can collapse to 0,
        # which forces the old fallback to actual_max and makes the capped
        # map look like a normal 0-to-max continuous ramp. Instead, calculate
        # the cap from positive values when they exist, so values above the
        # chosen percentile are truly saturated red while the remaining
        # nonzero values still receive a useful green-yellow-orange ramp.
        percentile = float(cap_percentile) / 100.0
        positive_vals = vals[vals > vmin]
        cap_source = positive_vals if not positive_vals.empty else vals
        cap = float(cap_source.quantile(percentile))
        if cap <= vmin:
            cap = actual_max
        if cap > actual_max:
            cap = actual_max
        return [vmin, cap], actual_max, cap

    if method == "Equal interval":
        step = (actual_max - vmin) / float(num_classes)
        breaks = [vmin + i * step for i in range(num_classes + 1)]
        return breaks, actual_max, actual_max

    if method == "Quantile":
        qs = [i / float(num_classes) for i in range(num_classes + 1)]
        breaks = [float(vals.quantile(q)) for q in qs]
        breaks[0] = vmin
        breaks[-1] = actual_max
        breaks = _unique_sorted_breaks(breaks)
        if len(breaks) < 2:
            breaks = [vmin, actual_max]
        return breaks, actual_max, actual_max

    if method == "Natural breaks":
        breaks = _jenks_breaks(vals.tolist(), num_classes)
        breaks[0] = vmin
        breaks[-1] = actual_max
        if len(breaks) < 2:
            breaks = [vmin, actual_max]
        return breaks, actual_max, actual_max

    if method == "Manual breaks":
        user_vals = []
        for part in str(manual_breaks_text).replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                user_vals.append(float(part))
            except Exception:
                pass
        user_vals = sorted(set(user_vals))
        breaks = [vmin] + [v for v in user_vals if vmin < v < actual_max] + [actual_max]
        breaks = _unique_sorted_breaks(breaks)
        if len(breaks) < 2:
            breaks = [vmin, actual_max]
        return breaks, actual_max, actual_max

    return [vmin, actual_max], actual_max, actual_max


def render_numeric_symbology_controls(label, key_prefix, default_method="Capped gradient"):
    with st.expander(f"{label} color / legend settings", expanded=False):
        method = st.selectbox(
            "Color classification method",
            NUMERIC_METHODS,
            index=NUMERIC_METHODS.index(default_method) if default_method in NUMERIC_METHODS else 0,
            key=f"{key_prefix}_classification_method",
        )

        num_classes = st.slider(
            "Number of classes",
            min_value=3,
            max_value=9,
            value=5,
            step=1,
            key=f"{key_prefix}_num_classes",
            disabled=method in ["Continuous gradient", "Capped gradient"],
        )

        cap_percentile = st.slider(
            "Cap percentile for capped gradient",
            min_value=80,
            max_value=100,
            value=95,
            step=1,
            key=f"{key_prefix}_cap_percentile",
            disabled=method != "Capped gradient",
            help="Values above this percentile use the highest color. The legend still shows the actual data maximum.",
        )

        manual_breaks = st.text_input(
            "Manual break values, comma-separated",
            value="",
            placeholder="Example: 5, 10, 20, 40",
            key=f"{key_prefix}_manual_breaks",
            disabled=method != "Manual breaks",
        )

        st.caption(
            "Continuous shows the full range. Capped protects the map from outliers. "
            "Quantile ranks features into equal-count groups. Manual breaks can match agency thresholds."
        )

    return {
        "method": method,
        "num_classes": int(num_classes),
        "cap_percentile": int(cap_percentile),
        "manual_breaks": manual_breaks,
    }



def _class_colors(n_classes):
    n_classes = max(1, int(n_classes))
    if n_classes == 1:
        return [CLASS_RAMP_COLORS[0]]
    last = len(CLASS_RAMP_COLORS) - 1
    return [
        CLASS_RAMP_COLORS[int(round(i * last / float(n_classes - 1)))]
        for i in range(n_classes)
    ]


def _midpoint_breaks_from_unique(values, max_classes=5):
    """Create value boundaries from unique values when quantile breaks collapse.

    This protects classed methods from all-green maps caused by many duplicate
    zeros or one extreme outlier. Example: [0, 7146] becomes
    [0, 3573, 7146], so 0 is low and 7146 is high.
    """
    unique_vals = sorted({float(v) for v in values if pd.notna(v)})
    if len(unique_vals) <= 1:
        base = unique_vals[0] if unique_vals else 0.0
        return [base, base + 1.0]

    if len(unique_vals) > max_classes:
        # Choose representative unique values by rank, then use midpoints
        # between those values as class boundaries.
        positions = [
            int(round(i * (len(unique_vals) - 1) / float(max_classes)))
            for i in range(max_classes + 1)
        ]
        chosen = []
        for pos in positions:
            val = unique_vals[max(0, min(pos, len(unique_vals) - 1))]
            if not chosen or val > chosen[-1]:
                chosen.append(val)
        unique_vals = chosen

    breaks = [unique_vals[0]]
    for left, right in zip(unique_vals[:-1], unique_vals[1:]):
        if right > left:
            breaks.append((left + right) / 2.0)
    breaks.append(unique_vals[-1])
    return _unique_sorted_breaks(breaks)


class ClassedColorMap:
    """Callable Folium-compatible classed color map with a discrete legend."""

    def __init__(self, breaks, colors, caption, actual_max=None, method=None):
        self.breaks = _unique_sorted_breaks(breaks)
        if len(self.breaks) < 2:
            self.breaks = [0.0, 1.0]
        self.colors = list(colors)[: max(1, len(self.breaks) - 1)]
        if len(self.colors) < len(self.breaks) - 1:
            self.colors = _class_colors(len(self.breaks) - 1)
        self.caption = caption
        self.actual_max = actual_max
        self.method = method

    def __call__(self, value):
        try:
            value = float(value)
        except Exception:
            value = self.breaks[0]
        if value >= self.breaks[-1]:
            return self.colors[-1]
        for i in range(len(self.breaks) - 1):
            lower = self.breaks[i]
            upper = self.breaks[i + 1]
            if lower <= value < upper:
                return self.colors[i]
        return self.colors[0]

    def _class_label(self, i):
        lower = self.breaks[i]
        upper = self.breaks[i + 1]
        if i == len(self.breaks) - 2:
            return f"{_fmt(lower)} - {_fmt(upper)}"
        return f"{_fmt(lower)} - <{_fmt(upper)}"

    def add_to(self, fmap):
        items = "".join(
            '<div style="white-space:nowrap;margin:2px 0;">'
            '<span style="display:inline-block;width:16px;height:10px;background:'
            + html.escape(str(self.colors[i]))
            + ';margin-right:6px;border:1px solid #777;"></span>'
            + html.escape(self._class_label(i))
            + '</div>'
            for i in range(len(self.breaks) - 1)
        )
        legend_html = f"""
        <div id="numeric-classed-legend" style="
            position: fixed;
            right: 34px;
            bottom: 35px;
            z-index: 9997;
            background: rgba(255, 255, 255, 0.94);
            padding: 8px 10px;
            border: 1px solid #888;
            border-radius: 4px;
            font-size: 11px;
            max-height: 220px;
            max-width: 285px;
            overflow-y: auto;
            box-shadow: 0 1px 4px rgba(0,0,0,0.25);
        ">
            <b>{html.escape(str(self.caption))}</b><br>
            {items}
        </div>
        """
        fmap.get_root().html.add_child(__import__("folium").Element(legend_html))
        return fmap


def make_numeric_colormap(values, cm, label, settings=None):
    settings = settings or {}
    method = settings.get("method", "Continuous gradient")
    num_classes = int(settings.get("num_classes", 5) or 5)
    cap_percentile = int(settings.get("cap_percentile", 95) or 95)
    manual_breaks = settings.get("manual_breaks", "")

    breaks, actual_max, color_max = compute_breaks(
        values,
        method,
        num_classes=num_classes,
        cap_percentile=cap_percentile,
        manual_breaks_text=manual_breaks,
    )

    max_label = _fmt(actual_max)

    if method in ["Equal interval", "Quantile", "Natural breaks", "Manual breaks"]:
        vals = _clean_values(values)
        desired_classes = max(2, min(num_classes, 9))

        # If duplicate values or outliers collapse the class breaks, rebuild
        # breaks from unique values. Without this, quantile can silently become
        # one class and the whole map appears green.
        if len(breaks) < 3 and not vals.empty and vals.nunique() > 1:
            breaks = _midpoint_breaks_from_unique(
                vals.tolist(),
                max_classes=desired_classes,
            )

        n_steps = max(1, len(breaks) - 1)
        colors = _class_colors(n_steps)
        caption = f"{label}: {method}; max = {max_label}"
        cmap = ClassedColorMap(
            breaks=breaks,
            colors=colors,
            caption=caption,
            actual_max=actual_max,
            method=method,
        )
        return cmap

    vmax = color_max if color_max > breaks[0] else breaks[0] + 1.0
    cmap = cm.LinearColormap(
        colors=["green", "yellow", "orange", "red"],
        vmin=breaks[0],
        vmax=vmax,
    )

    # Keep the legend caption short. Always show the actual data max, and
    # show the cap when used.
    if method == "Capped gradient" and actual_max > color_max:
        cmap.caption = f"{label}: Capped P{cap_percentile} = {_fmt(color_max)}; max = {max_label}"
    elif method == "Capped gradient":
        cmap.caption = f"{label}: Capped gradient; max = {max_label}"
    else:
        cmap.caption = f"{label}: Continuous; max = {max_label}"

    return cmap


def _preferred_crash_columns(crashes):
    if crashes is None or crashes.empty:
        return []
    groups = [
        ["Year", "CrashYear", "caseyear", "CaseYear", "YEAR"],
        # Prefer original mapped severity labels for legends.  The normalized
        # KABCO field remains available for calculations, but map legends should
        # show labels from the user's severity column when available.
        ["DashboardSeverityLabel", "CrashSeverityLabel", "Severity", "severity", "CrashSeverity", "CRASH_SEVERITY", "INJURY_SEVERITY", "KABCO"],
        ["CrashType", "Crash_Type", "crash_type", "MannerCollision", "FirstHarmfulEvent", "UnitType"],
    ]
    cols = []
    for group in groups:
        for col in group:
            if col in crashes.columns and col not in cols:
                cols.append(col)
    for col in crashes.columns:
        if col == "geometry" or col in cols:
            continue
        try:
            nunique = crashes[col].dropna().astype(str).nunique()
        except Exception:
            nunique = 999
        if 1 < nunique <= 20:
            cols.append(col)
    return cols


def render_crash_color_controls(crashes, key_prefix="crash_map"):
    with st.expander("Crash point color settings", expanded=False):
        enabled = st.checkbox(
            "Color crash points by attribute",
            value=False,
            key=f"{key_prefix}_color_enabled",
        )
        columns = _preferred_crash_columns(crashes)
        if enabled and not columns:
            st.warning("No suitable crash attribute column was found for coloring.")
            enabled = False
            field = None
        elif enabled:
            field = st.selectbox(
                "Color crashes by",
                options=columns,
                key=f"{key_prefix}_color_field",
            )
            st.caption("Leave this unchecked to show crash points with the default single color.")
        else:
            field = None
            st.caption("Default crash color is used unless this option is enabled.")
    return {"enabled": bool(enabled and field), "field": field}


def categorical_color_lookup(values):
    cats = sorted({str(v) for v in values if pd.notna(v) and str(v).strip() != ""})
    return {cat: CATEGORY_COLORS[i % len(CATEGORY_COLORS)] for i, cat in enumerate(cats)}


def add_categorical_legend(fmap, title, color_lookup, element_id="category-legend"):
    if not color_lookup:
        return fmap

    element_id_clean = str(element_id)
    if "crash" in element_id_clean.lower():
        # Stack crash-attribute legends above the road class legend. The road
        # class legend uses bottom:45px and can be up to about 240px tall.
        bottom_px = 305
        z_index = 10000
        max_height = 190
    else:
        bottom_px = 45
        z_index = 9998
        max_height = 230

    items = "".join(
        '<div style="white-space:nowrap;"><span style="display:inline-block;width:10px;height:10px;background:'
        + html.escape(str(color))
        + ';margin-right:5px;border:1px solid #777;"></span>'
        + html.escape(str(cat))
        + '</div>'
        for cat, color in color_lookup.items()
    )
    legend_html = f"""
    <div id="{html.escape(element_id_clean)}" style="
        position: fixed;
        bottom: {bottom_px}px;
        left: 42px;
        z-index: {z_index};
        background: rgba(255, 255, 255, 0.94);
        padding: 7px 9px;
        border: 1px solid #888;
        border-radius: 4px;
        font-size: 11px;
        max-height: {max_height}px;
        max-width: 270px;
        overflow-y: auto;
        box-shadow: 0 1px 4px rgba(0,0,0,0.25);
    ">
        <b>{html.escape(str(title))}</b><br>
        {items}
    </div>
    """
    fmap.get_root().html.add_child(__import__("folium").Element(legend_html))
    return fmap


def crash_marker_style(row, crash_color_settings=None):
    crash_color_settings = crash_color_settings or {}
    if not crash_color_settings.get("enabled"):
        return "red", None
    field = crash_color_settings.get("field")
    lookup = crash_color_settings.get("color_lookup") or {}
    if field is None or field not in row.index:
        return "red", None
    value = row[field]
    key = str(value) if pd.notna(value) else "Unknown"
    return lookup.get(key, "red"), key
