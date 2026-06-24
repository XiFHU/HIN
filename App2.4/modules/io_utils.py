# modules/io_utils.py
"""
Upload readers for HIN Streamlit app.

Version marker shown in the UI:
UPLOAD_READER_VERSION = "RUN_THIS_ONLY_V5_2026_06_22"

This file avoids the old Windows bug caused by writing an uploaded ZIP to
Path(temp_dir) / uploaded_file.name. ZIPs are read from bytes and extracted to a
safe internal folder instead.
"""

import io
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import geopandas as gpd

UPLOAD_READER_VERSION = "RUN_THIS_ONLY_V5_2026_06_22"

REQUIRED_SHP_EXTS = [".shp", ".shx", ".dbf"]
OPTIONAL_SHP_EXTS = [".prj", ".cpg"]
ALL_SHP_EXTS = REQUIRED_SHP_EXTS + OPTIONAL_SHP_EXTS

HELP_TEXT = (
    "Upload a zipped shapefile or upload the shapefile components together: "
    ".shp, .shx, .dbf, and preferably .prj."
)


def _as_list(uploaded_files):
    if uploaded_files is None:
        return []
    if isinstance(uploaded_files, (list, tuple)):
        return list(uploaded_files)
    return [uploaded_files]


def _upload_bytes(uploaded_file):
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    if hasattr(uploaded_file, "getbuffer"):
        return bytes(uploaded_file.getbuffer())
    data = uploaded_file.read()
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    return data


def _safe_member_name(member_name):
    cleaned = str(member_name).replace("\\", "/")
    path = Path(cleaned)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe path inside ZIP: {member_name}")
    return path


def _extract_zip_bytes(zip_bytes, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zip_ref:
            bad_file = zip_ref.testzip()
            if bad_file is not None:
                raise ValueError(f"The ZIP file appears damaged near: {bad_file}")

            for member in zip_ref.infolist():
                member_path = _safe_member_name(member.filename)
                target_path = output_dir / member_path

                if member.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue

                target_path.parent.mkdir(parents=True, exist_ok=True)

                if target_path.exists() and target_path.is_dir():
                    raise ValueError(
                        "The ZIP contains both a folder and a file with the same path: "
                        f"{member.filename}. Re-zip only the shapefile files and try again."
                    )

                with zip_ref.open(member, "r") as source:
                    target_path.write_bytes(source.read())

    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a readable ZIP. " + HELP_TEXT) from exc


def _find_by_suffix(folder, suffix):
    suffix = suffix.lower()
    return sorted(
        path for path in Path(folder).rglob("*")
        if path.is_file() and path.suffix.lower() == suffix
    )


def _sidecar_exists(shp_path, ext):
    parent = Path(shp_path).parent
    stem = Path(shp_path).stem.lower()
    ext = ext.lower()
    for item in parent.iterdir():
        if item.is_file() and item.stem.lower() == stem and item.suffix.lower() == ext:
            return True
    return False


def _find_valid_shp(folder, prefer_place=False):
    shp_files = _find_by_suffix(folder, ".shp")
    if not shp_files:
        found = sorted({p.suffix.lower() for p in Path(folder).rglob("*") if p.is_file()})
        raise ValueError(
            "No .shp file was found in the upload. "
            f"File extensions found: {found}. {HELP_TEXT}"
        )

    valid = []
    notes = []
    for shp_path in shp_files:
        missing = [ext for ext in REQUIRED_SHP_EXTS if not _sidecar_exists(shp_path, ext)]
        if missing:
            notes.append(f"{shp_path.name} missing {', '.join(missing)}")
        else:
            valid.append(shp_path)

    if not valid:
        detail = "; ".join(notes[:8])
        raise ValueError("A .shp file was found, but sidecar files are missing. " + detail + ". " + HELP_TEXT)

    if prefer_place:
        keywords = ["place", "places", "plc", "tl_"]
    else:
        keywords = ["roads", "road", "street", "streets", "edges", "tl_", "line"]

    for keyword in keywords:
        matches = [p for p in valid if keyword in p.name.lower()]
        if matches:
            return matches[0]

    return valid[0]


def _read_path(path):
    path = Path(path)
    if path.suffix.lower() not in [".shp", ".gpkg", ".geojson", ".json"]:
        raise ValueError(f"Unsupported vector file: {path.name}")
    gdf = gpd.read_file(path)
    if gdf is None or gdf.empty:
        raise ValueError(f"The file loaded but contains no features: {path.name}")
    return gdf


def load_vector(uploaded_file, prefer_place=False):
    """Load one uploaded vector file: ZIP shapefile, GPKG, GeoJSON, or JSON."""
    if uploaded_file is None:
        raise ValueError("No file was uploaded.")

    suffix = Path(uploaded_file.name).suffix.lower()

    if suffix == ".zip":
        return load_zipped_shapefile(uploaded_file, prefer_place=prefer_place)

    if suffix in [".gpkg", ".geojson", ".json"]:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_path = Path(temp_dir) / ("uploaded_vector" + suffix)
            out_path.write_bytes(_upload_bytes(uploaded_file))
            return _read_path(out_path)

    if suffix in ALL_SHP_EXTS:
        raise ValueError("A single shapefile component is not enough. " + HELP_TEXT)

    raise ValueError(f"Unsupported vector format: {suffix}. {HELP_TEXT}")


def load_zipped_shapefile(uploaded_file, prefer_place=False):
    """Read a zipped shapefile without writing to uploaded_file.name."""
    with tempfile.TemporaryDirectory() as temp_dir:
        extract_dir = Path(temp_dir) / "extracted_zip"
        _extract_zip_bytes(_upload_bytes(uploaded_file), extract_dir)
        shp_path = _find_valid_shp(extract_dir, prefer_place=prefer_place)
        return _read_path(shp_path)


def load_uploaded_shapefile_components(uploaded_files, prefer_place=False):
    """
    Load from one ZIP, one GPKG/GeoJSON/JSON, or separate shapefile components.
    This is the function used by the custom road uploader.
    """
    files = _as_list(uploaded_files)
    if not files:
        raise ValueError("No files were uploaded. " + HELP_TEXT)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        component_dir = temp_dir / "components"
        component_dir.mkdir(parents=True, exist_ok=True)

        # Single file path: ZIP/GPKG/GeoJSON/JSON.
        if len(files) == 1:
            suffix = Path(files[0].name).suffix.lower()
            if suffix == ".zip":
                return load_zipped_shapefile(files[0], prefer_place=prefer_place)
            if suffix in [".gpkg", ".geojson", ".json"]:
                out_path = temp_dir / ("uploaded_vector" + suffix)
                out_path.write_bytes(_upload_bytes(files[0]))
                return _read_path(out_path)

        # Multiple file path: copy components using their original base names.
        for uploaded_file in files:
            safe_name = Path(uploaded_file.name).name
            suffix = Path(safe_name).suffix.lower()

            if suffix == ".zip":
                zip_dir = temp_dir / f"zip_{len(list(temp_dir.glob('zip_*')))}"
                _extract_zip_bytes(_upload_bytes(uploaded_file), zip_dir)
                continue

            if suffix in ALL_SHP_EXTS:
                (component_dir / safe_name).write_bytes(_upload_bytes(uploaded_file))
                continue

            if suffix in [".gpkg", ".geojson", ".json"]:
                out_path = temp_dir / ("uploaded_vector" + suffix)
                out_path.write_bytes(_upload_bytes(uploaded_file))
                return _read_path(out_path)

            raise ValueError(f"Unsupported uploaded file: {safe_name}. {HELP_TEXT}")

        shp_path = _find_valid_shp(temp_dir, prefer_place=prefer_place)
        return _read_path(shp_path)


def load_crash_file(uploaded_file):
    """Load crash CSV or Excel file."""
    suffix = Path(uploaded_file.name).suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(uploaded_file)

    if suffix in [".xlsx", ".xls"]:
        return pd.read_excel(uploaded_file)

    raise ValueError("Unsupported crash format. Please upload CSV, XLSX, or XLS.")


def save_gpkg(gdf, output_path, layer_name="output"):
    """Save GeoDataFrame to GeoPackage."""
    gdf.to_file(output_path, layer=layer_name, driver="GPKG")
