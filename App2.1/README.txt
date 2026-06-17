# Corridor GIS Analysis Tool

Interactive Streamlit application for transportation corridor analysis, crash visualization, and GIS data exploration.

## Overview

This application allows users to upload transportation-related GIS datasets and perform corridor analysis through an interactive web interface.

Key capabilities include:

* Road network visualization
* Corridor identification
* Traffic signal mapping
* Crash data visualization
* Crash classification analysis
* Interactive GIS mapping
* Layer control and filtering

## Project Structure

```text
corridor-gis-tool/
│
├── app.py
├── requirements.txt
├── README.md
│
└── modules/
    ├── io_utils.py
    ├── roads.py
    ├── signals.py
    ├── corridors.py
    ├── crashes.py
    ├── crash_classification.py
    └── visualization.py
```

## Requirements

Python 3.10 or newer is recommended.

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running Locally

Start the Streamlit application:

```bash
streamlit run app.py
```

The application will open in your web browser.

## Data Input

Users upload their own datasets directly through the application.

Supported GIS formats may include:

* GeoPackage (.gpkg)
* GeoJSON (.geojson)
* Shapefile (.shp)
* CSV (.csv)
* Excel (.xlsx)

No sample data is required for deployment.

## Deployment

This application can be deployed using:

* Streamlit Community Cloud
* Azure App Service
* AWS
* Internal servers

For Streamlit Cloud:

1. Push this repository to GitHub.
2. Create a new Streamlit app.
3. Select the repository.
4. Set `app.py` as the entry point.
5. Deploy.

## Notes

* Uploaded files are processed during the user session.
* No local data folders are required.
* Users must provide their own datasets.
* Large GIS datasets may require additional processing time.

## Author

Xi Wei
Felsburg Holt & Ullevig, Inc