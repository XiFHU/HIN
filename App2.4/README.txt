HIN Corridor / Intersection / Segment Safety Analysis App
=========================================================

Overview
--------

This Streamlit app supports roadway safety screening using crash data, road networks, traffic signals, corridors, intersections, road segments, crash density, HIN priority scoring, and dashboard/report outputs.

The app is organized around three spatial-unit workflows:

1. Intersection — builds signalized intersection units from traffic signals and analyzes crash concentration around intersections.
2. Corridor — builds corridors from signalized routes and analyzes corridor-level crash density.
3. Segment — analyzes road segments and supports Sliding Window / HIN priority analysis across all selected road segments.

The app is designed so normal users can run the workflow with default settings, while advanced threshold controls are hidden inside optional settings panels.

Main Dependencies
-----------------

Install dependencies from requirements.txt:

pip install -r requirements.txt

Common packages used by the app include:

- streamlit
- geopandas
- pandas
- numpy
- shapely
- folium
- streamlit-folium
- plotly
- openpyxl
- python-docx
- kaleido for PNG/JPG chart export

If PNG export does not work, install Kaleido:

pip install kaleido


Folder Structure
----------------

The app is organized as a modular Streamlit project:

App/
├── app2.10.py
├── requirements.txt
├── modules/
│   ├── io_utils.py
│   ├── defaults.py
│   ├── corridors.py
│   ├── signals.py
│   ├── visualization.py
│   └── ...
├── ui/
│   ├── workflows.py
│   ├── workflow_shared.py
│   ├── intersection.py
│   ├── corridor.py
│   ├── segment.py
│   └── steps/
│       ├── roads.py
│       ├── signals.py
│       ├── corridors.py
│       ├── crashes.py
│       ├── results.py
│       ├── sliding_window.py
│       ├── visualization.py
│       ├── downloads.py
│       └── dashboard.py
└── README.txt


Workflow Summary
----------------

The app uses a simplified five-step workflow:

1. Road Network / Data Setup
2. Build Spatial Units
3. Analysis
4. Visualization
5. Dashboard / Downloads / Report

Most technical thresholds use default values automatically. Users only need to open optional settings if they want to customize them.


Step 1: Road Network / Data Setup
---------------------------------

Supported Road Sources
----------------------

The app supports three road-source options:

1. Upload custom road network
2. Use TIGER roads + PLACE boundary
3. Use OSM roads — no upload

Supported Upload Formats
------------------------

Custom road uploads can include:

- Zipped shapefile: .zip
- Shapefile components uploaded together: .shp, .shx, .dbf, .prj, optional .cpg
- GeoPackage: .gpkg
- GeoJSON: .geojson or .json

For shapefiles, upload all required parts together:

roads.shp
roads.shx
roads.dbf
roads.prj

The ZIP loader is designed to read shapefile ZIPs safely from memory and avoid Windows temp-folder permission errors.

Road Class Filter
-----------------

The Road Class Filter is optional.

When enabled, the user selects a road classification field from the uploaded or downloaded road network. The dashboard road-class chart only appears when this filter is enabled.

The road-class chart uses the exact column selected in Step 1. It does not use unrelated fields such as traffic-signal attributes.

Potential road-class fields may include:

- TIGER-style fields such as road type / MTFCC / RTTYP, depending on the dataset
- OSM-style fields such as highway
- Uploaded-road fields such as FunctionalClass, RoadClass, CLASS, or similar


Step 2: Build Spatial Units
---------------------------

Spatial units depend on the selected workflow.

Intersection Workflow
---------------------

The app generates signalized intersection units from traffic signal points.

Typical process:

1. Load or fetch signal points.
2. Remove duplicate signals using a default duplicate-distance threshold.
3. Build signalized intersection buffers or polygons.
4. Prepare intersection units for crash joining and crash-density analysis.

Signals are required to build intersection units. Only the threshold settings are optional.

Corridor Workflow
-----------------

The app builds corridors from signals and roads.

Typical process:

1. Generate or load signals.
2. Assign signals to nearby roads.
3. Group valid signalized routes into corridors.
4. Build corridor geometries.
5. Optionally drop corridors by ID.
6. Store both all generated corridors and filtered/final corridors.

Signals are required to build corridors. Corridor thresholds are optional.

Segment Workflow
----------------

The app uses road segments as the spatial units.

In V20+ and current version, segment crash classification and Sliding Window/HIN analysis use all selected road segments, not only roads inside final corridors.

This prevents losing segment-level results outside corridor context.


Step 3: Analysis
----------------

Crash Density Analysis
----------------------

Crash density is the main result for intersection, corridor, and segment workflows.

The general concept is:

Crash Density = Crash Count / Exposure Unit

For intersections, the exposure unit is typically the intersection spatial unit. For corridors and segments, the exposure unit is typically length in miles.

Crash-density results are considered analysis results. Therefore:

- Intersection results are ready after crash-density analysis.
- Corridor results are ready after crash-density analysis.
- Segment results are ready after crash-density analysis.
- Sliding Window/HIN results are additional segment-priority results.

Sliding Window / HIN Analysis
-----------------------------

Sliding Window analysis is mainly for the Segment workflow.

The app generates moving windows along routes and calculates HIN priority values. In the latest versions, Sliding Window analysis is designed to use all selected road segments rather than only corridor roads.

The Sliding Window step keeps key settings visible because those settings define the method:

- Window length
- Step size
- HIN / risk metric
- Ranking or priority method

Less important thresholds are hidden or moved to Visualization.


Step 4: Visualization
---------------------

The Visualization section displays result maps without overwriting the analysis tables.

Visualization filters are display-only. They do not change the saved result data.

Common filters include:

- Minimum crash count
- Show all features
- Top N
- Top X percent
- Top X percent of length/network miles

Crash Density Map
-----------------

The Crash Density Map shows spatial units colored by crash density.

It uses the same general color meaning throughout the workflow and dashboard:

Green  = lower value
Yellow = moderate value
Orange = high value
Red    = highest value

Crash Density Threshold / Summary Map
-------------------------------------

This is a screening view based on the same crash-density result. It can show units above average, above median, or other summary thresholds.

It does not create a new analysis result; it only summarizes or filters the existing crash-density result.

HIN Priority Map
----------------

The HIN Priority Map shows segments or windows by HIN priority index.

It uses the same low-to-high color meaning:

Green  = lower priority
Yellow = moderate priority
Orange = high priority
Red    = highest priority

Dashboard Map Layers
--------------------

Dashboard maps can include optional context layers:

- Roads
- Road class layer
- Signals
- Crash points
- Corridors
- Generated corridors
- Study boundary

Dashboard map views are read-only. Editing and filtering should be done in the main workflow and Visualization section.

Map Auto-Zoom
-------------

Current versions improve dashboard map zoom behavior:

- Dashboard maps reset when result bounds change.
- Crash-density maps try to auto-fit to the selected result layer.
- HIN maps try to auto-fit to the selected result layer.
- Corridor maps auto-fit to corridor geometry.

If a map still opens at the wrong scale, refresh the Streamlit page after the result layer is available.


Step 5: Dashboard, Downloads, and Reports
-----------------------------------------

Crash Insights Dashboard
------------------------

The Crash Insights dashboard is the main results dashboard.

It includes default safety-analysis figures such as:

- Crashes by year
- Crash type pie/donut chart
- KABCO / severity distribution
- Road-class chart when the Step 1 road-class filter is enabled
- Top spatial units by crash density
- Top spatial units by crash count
- HIN priority ranking when HIN results are available

The manual Chart Builder tab was removed in V19. The workflow is now closer to a fixed safety dashboard:

1. Crash Insights displays the main figures.
2. Dashboard Builder lets users choose which charts/maps to include in the final dashboard/report.
3. Dashboard Assistant can help create chart/report requests using natural language.

Dashboard Builder
-----------------

The Dashboard Builder lets users select specific charts, tables, and maps to include in the dashboard export/report.

Typical selectable items include:

- Crashes by year
- Crash type share
- KABCO distribution
- Road-class summary when available
- Top crash-density spatial units
- Top crash-count spatial units
- HIN priority ranking
- Crash density map
- HIN priority map
- Corridor map

Dashboard Assistant
-------------------

The Dashboard Assistant is a simple natural-language helper.

Examples:

Show KABCO distribution.

Create a dashboard with crash year trend, crash type chart, top risky units, and crash density map.

Count crashes in each intersection colored by crash type.

The assistant uses rule-based and fuzzy matching logic. It does not require model training.

If the assistant cannot confidently match a user request to a column, it should ask the user to choose the exact column from the dataset.


Downloads
---------

The app supports result downloads such as:

- CSV result tables
- Excel result tables
- GeoJSON / GIS outputs when available
- Word report
- PNG dashboard summary

For corridor workflows, downloads should distinguish between:

1. All generated corridors
2. Filtered/final corridors after dropped corridors are removed

For segment and HIN workflows, downloads should avoid names like section7 and instead use clear names such as:

hin_risk_segments.csv
hin_sliding_window_results.xlsx
hin_corridors.csv


Table Context Fields
--------------------

Result tables should include useful context fields when available.

Intersection tables should include:

- Spatial unit id
- Unit type
- City
- Crash count
- Crash density
- Road 1
- Road 2

Corridor tables should include:

- Corridor ID
- Route name
- City
- Length
- Crash count
- Crash density

Segment tables should include:

- Segment ID
- Route name
- City
- Length
- Crash count
- Crash density
- HIN priority index, when HIN results exist


Word Report Export
------------------

The Word report is intended to include:

- Narrative summary text
- Key charts
- Clean result tables
- Selected dashboard map images

The report should focus on decision-ready outputs, not raw uploaded tables.

Recommended report tables include:

Top crash-density spatial units
-------------------------------

Recommended columns:

Rank
Spatial unit id
Unit type
City
Length_mi
Crash count
Crash density

Severity summary by spatial unit
--------------------------------

Recommended columns:

Rank
Spatial unit id
K
A
B
C
O
Total

Top HIN / risk spatial units
----------------------------

Recommended columns:

Rank
Spatial unit id
HIN priority index
Crash count

The report should avoid using length, density, or score fields as the spatial unit ID.


Clear History / Start Over
--------------------------

The app includes a Clear history / Start over button near the workflow selector.

This button should clear Streamlit session state and restart the workflow so users can begin a new analysis without old results, old map settings, or old dashboard selections interfering.


Important Notes About Spatial Unit IDs
--------------------------------------

Spatial unit ranking charts and report tables should use meaningful spatial-unit IDs.

Examples:

INT_93
COR_12
SEGROW_4382

They should not use fields like:

SegmentLength_Mile
CrashDensity
HIN_Priority_Index

as the y-axis ID or spatial unit identifier.


Known Limitations
-----------------

Direct click-to-delete corridors from the map
---------------------------------------------

The stable app uses ID-based corridor deletion.

Directly clicking a corridor on a Folium map and deleting it would require custom JavaScript callbacks. That is possible, but less stable in regular Streamlit/Folium.

Static map export
-----------------

Static map images in Word reports are generated from selected map layers. Some web-map basemap tiles may not export exactly like the interactive map depending on local rendering and package support.

Natural-language dashboard assistant
------------------------------------

The assistant uses rule-based and fuzzy matching logic. It is not a trained model.

This is usually better for this app because the expected domain terms are known:

crash type
crash year
KABCO
severity
crash count
crash density
HIN
road class
intersection
corridor
segment


Recommended User Workflow
-------------------------

Intersection Analysis
---------------------

1. Choose Intersection.
2. Load roads, boundary, crashes, and signals.
3. Generate signals/intersections.
4. Run crash-density analysis.
5. View Crash Density Map.
6. Open Dashboard.
7. Review crash year, crash type, KABCO, crash-density ranking, and maps.
8. Export Word report or PNG summary.

Corridor Analysis
-----------------

1. Choose Corridor.
2. Load roads, boundary, crashes, and signals.
3. Generate signals.
4. Build corridors.
5. Optionally drop corridors by ID.
6. Run crash-density analysis.
7. View final corridor and crash-density maps.
8. Export all generated corridors and filtered/final corridors.
9. Export dashboard/report.

Segment / HIN Analysis
----------------------

1. Choose Segment.
2. Load roads and crashes.
3. Run segment crash-density analysis using all selected road segments.
4. Run Sliding Window / HIN analysis.
5. View Crash Density Map and HIN Priority Map.
6. Open Dashboard.
7. Review crash-density ranking, crash-count ranking, and HIN priority ranking.
8. Export dashboard/report.




Shapefile ZIP upload fails
--------------------------

Make sure the ZIP contains at least:

.shp
.shx
.dbf
.prj

If possible, use GeoPackage .gpkg, which is more reliable than shapefile ZIP.

Dashboard map opens at world scale
----------------------------------

Try refreshing after results are ready. The map should auto-fit after the result layer is available.

Also confirm the result layer has a valid CRS and geometry.

PNG export does not work
------------------------

Install Kaleido:

pip install kaleido

Streamlit table gives a PyArrow error
-------------------------------------

This can happen when a column has mixed object types. The app includes sanitization logic for display tables, but if the issue appears again, convert mixed columns to strings before calling st.dataframe().


Suggested Future Improvements
-----------------------------

Potential future versions could add:

- More stable map-to-report screenshot capture.
- Better direct map selection for corridors or spatial units.
- Click chart bar to highlight map feature.
- More advanced dashboard assistant intent parsing.
- Saved dashboard templates.
- User-defined report templates.
- Export full dashboard to standalone HTML with embedded maps and charts.
