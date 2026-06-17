# modules/exports.py

import os
import zipfile
import tempfile


def prepare_for_shapefile(gdf):
    """
    Remove problematic fields for Shapefile.
    """

    keep_cols = [
        c for c in [
            "CrashID",
            "SignalID",
            "UnitID",
            "UnitType",
            "IntersectionID",
            "SegmentID",
            "CorridorID",
            "Route",
            "RoadName1",
            "RoadName2",
            "City",
            "CrashCount",
            "KABCO",
            "Severity",
            "geometry"
        ]
        if c in gdf.columns
    ]

    return gdf[keep_cols].copy()


def export_gpkg_bytes(
    gdf,
    filename="output.gpkg"
):
    """
    Return GeoPackage bytes for Streamlit download.
    """

    with tempfile.TemporaryDirectory() as temp_dir:

        path = os.path.join(
            temp_dir,
            filename
        )

        gdf.to_file(
            path,
            driver="GPKG"
        )

        with open(path, "rb") as f:
            return f.read()


def export_shapefile_zip_bytes(
    gdf,
    basename="output"
):
    """
    Return zipped shapefile bytes.
    """

    with tempfile.TemporaryDirectory() as temp_dir:

        shp_path = os.path.join(
            temp_dir,
            f"{basename}.shp"
        )

        prepare_for_shapefile(
            gdf
        ).to_file(shp_path)

        zip_path = os.path.join(
            temp_dir,
            f"{basename}.zip"
        )

        with zipfile.ZipFile(
            zip_path,
            "w",
            zipfile.ZIP_DEFLATED
        ) as zipf:

            for file in os.listdir(temp_dir):

                if file.startswith(
                    f"{basename}."
                ):

                    zipf.write(
                        os.path.join(
                            temp_dir,
                            file
                        ),
                        arcname=file
                    )

        with open(zip_path, "rb") as f:
            return f.read()


def export_csv_bytes(df):
    """
    Return CSV bytes.
    """

    return df.to_csv(
        index=False
    ).encode("utf-8")
