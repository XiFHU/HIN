# modules/io_utils.py

import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import geopandas as gpd


def load_vector(uploaded_file):
    """
    Load vector files for Streamlit uploads.

    Supports:
    - zipped shapefile .zip
    - .gpkg
    - .geojson
    - .json
    """

    suffix = Path(uploaded_file.name).suffix.lower()

    if suffix == ".zip":
        return load_zipped_shapefile(uploaded_file)

    if suffix in [".gpkg", ".geojson", ".json"]:
        return gpd.read_file(uploaded_file)

    if suffix == ".shp":
        raise ValueError(
            "A single .shp file is not enough. "
            "Please upload the full TIGER shapefile as a .zip."
        )

    raise ValueError(f"Unsupported vector format: {suffix}")


def load_zipped_shapefile(uploaded_file):
    """
    Extract uploaded .zip shapefile and read the .shp inside.
    """

    temp_dir = tempfile.mkdtemp()

    zip_path = Path(temp_dir) / uploaded_file.name

    with open(zip_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(temp_dir)

    shp_files = list(Path(temp_dir).rglob("*.shp"))

    if not shp_files:
        raise ValueError("No .shp file found inside the uploaded zip.")

    return gpd.read_file(shp_files[0])


def load_crash_file(uploaded_file):
    """
    Load crash CSV or Excel file.
    """

    suffix = Path(uploaded_file.name).suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(uploaded_file)

    if suffix in [".xlsx", ".xls"]:
        return pd.read_excel(uploaded_file)

    raise ValueError(
        "Unsupported crash format. Please upload CSV, XLSX, or XLS."
    )


def save_gpkg(gdf, output_path, layer_name="output"):
    """
    Save GeoDataFrame to GeoPackage.
    """

    gdf.to_file(
        output_path,
        layer=layer_name,
        driver="GPKG"
    )
