"""Default threshold settings used by the simplified UI.

Normal users do not need to edit these. Each workflow step exposes them only
inside an Optional settings expander.
"""

SIGNAL_DEFAULTS = {
    "duplicate_signal_distance_m": 45,
    "road_snap_distance_ft": 300,
}

CORRIDOR_DEFAULTS = {
    "min_signals_for_corridor": 3,
    "nearest_road_distance_m": 100,
    "corridor_width_m": 20,
    "corridor_search_buffer_m": 200,
}

CRASH_JOIN_DEFAULTS = {
    "intersection_search_distance_ft": 250,
    "corridor_search_distance_ft": 250,
    "segment_search_distance_ft": 250,
}

VISUALIZATION_DEFAULTS = {
    "min_crash_count": 0,
    "priority_mode": "All units",
    "top_percent": 10.0,
    "top_n": 20,
}

SLIDING_WINDOW_DEFAULTS = {
    "window_len_mi": 0.5,
    "step_len_mi": 0.1,
    "segment_length_mi": 0.1,
    "top_percent": 10,
    "crash_snap_dist_ft": 250,
}
