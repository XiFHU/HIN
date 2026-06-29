HIN Corridor / Intersection / Segment Safety Analysis App
=========================================================


Overview
--------
This Streamlit app supports roadway safety screening for intersections, corridors, and road segments. It combines crash data, road networks, traffic signals, corridor generation, crash-density analysis, Sliding Window / HIN priority scoring, visualization maps, dashboard charts, and Word/PNG report export.

The app is designed for two types of users:

1. Regular users who want to run the workflow with default settings.
2. Advanced users who want to adjust optional thresholds, map filters, dashboard selections, and report outputs.

Most technical thresholds are hidden in optional settings panels so the main workflow stays simple.

Main things the app can do
--------------------------
The app can:

- Load crash data from CSV or similar tabular files.
- Load custom road networks from shapefile ZIPs, shapefile components, GeoPackage, or GeoJSON.
- Use TIGER roads with a PLACE boundary.
- Use OSM roads without requiring a road upload.
- Load, fetch, clean, and de-duplicate traffic signal data from OSM.
- Build signalized intersection spatial units.
- Build signalized corridors from signals and road routes.
- Use road segments as spatial units.
- Generate FromMile and ToMile values automatically.
- Join crashes to intersections, corridors, or road segments.
- Calculate crash count and crash density.
- Run Sliding Window / HIN priority analysis for segment workflows.
- Display crash-density maps and HIN priority maps.
- Filter maps by minimum crash count, top N, top percent, or top percent of length/miles.
- Show dashboard crash patterns, severity patterns, route/segment rankings, and HIN summaries.
- Normalize severity fields from KABCO-style data or FARS-style/person-count data.
- Export CSV, Excel, GeoJSON, PNG summaries, and Word reports.
- Create dashboard reports with selected charts, tables, and map layers.
- Clear history / start over from the workflow page.

Recommended run command
-----------------------
Always run the app from inside the App folder. This avoids Python importing older ui or modules folders from another extracted version.

Example:

cd /d "C:\path\to\App"
python -m streamlit run app.py

If your folder name is different, change the path before \App.

Avoid running only with a full file path such as:

streamlit run "C:\path\to\App\app.py"

That can sometimes make Python import old modules from another folder.

Dependencies
------------
Install dependencies from requirements.txt:

pip install -r requirements.txt

Important packages include:

- streamlit
- pandas
- geopandas
- numpy
- shapely
- folium
- streamlit-folium
- plotly
- kaleido
- python-docx
- openpyxl
- pyproj
- fiona or pyogrio, depending on the environment

If Streamlit Cloud reports that Plotly is missing, make sure requirements.txt includes:

plotly

If PNG chart export does not work, install or add:

kaleido

Recommended folder structure
----------------------------
The app should look generally like this:

App/
  app2.4.py
  requirements.txt
  README.txt
  modules/
    io_utils.py
    defaults.py
    corridors.py
    signals.py
    visualization.py
    ...
  ui/
    workflows.py
    workflow_shared.py
    intersection.py
    corridor.py
    segment.py
    steps/
      roads.py
      signals.py
      corridors.py
      crashes.py
      results.py
      sliding_window.py
      visualization.py
      downloads.py
      dashboard.py

Workflow options
----------------
The app has three main workflow modes:

1. Intersection
2. Corridor
3. Segment

Each workflow uses the same general structure:

1. Road Network / Data Setup
2. Build Spatial Units
3. Analysis
4. Visualization
5. Dashboard / Downloads / Report

Step 1 - Road Network / Data Setup
----------------------------------
The app supports three road-source options:

1. Upload custom road network
2. Use TIGER roads plus PLACE boundary
3. Use OSM roads with no road upload

Supported custom road uploads include:

- Zipped shapefile: .zip
- Shapefile components uploaded together: .shp, .shx, .dbf, .prj, optional .cpg
- GeoPackage: .gpkg
- GeoJSON: .geojson or .json

For shapefiles, upload all required parts together:

roads.shp
roads.shx
roads.dbf
roads.prj

The upload loader is designed to avoid common Windows temp-folder permission errors when reading shapefile ZIPs.

Road class filter
-----------------
The Road Class Filter is optional.

When enabled, the user selects the road-class field from the road network. The dashboard road-class charts only appear when this filter is enabled and the selected field is available in the analysis data.

Possible road-class fields include:

- OSM: highway
- TIGER: MTFCC, RTTYP, road type, or similar fields depending on the source
- Uploaded roads: FunctionalClass, RoadClass, CLASS, FC, or similar local fields


Crash data
----------
Crash data can come from local CSV files or other supported table formats. The app expects crash records to have location information or geometry that can be spatially joined to road/intersection/corridor units.

The app tries to detect co
mmon crash-related columns, including:

- Crash ID or case ID
- Crash date
- Crash year
- Crash month
- Crash type / collision manner
- KABCO or severity
- Fatalities
- Serious injuries
- Level A injuries
- Level B injuries
- Level C injuries
- Uninjured / no injury / PDO

FARS-style data support
-----------------------
The app includes logic for FARS-style datasets.

For example, if a FARS file has fields like:

- year
- monthname
- man_collname
- fatals
- fatalities
- Level A Injuries
- Level B Injuries
- Level C Injuries
- Uninjured

then the app should try to normalize these into the dashboard logic.

Crash type detection should recognize columns that contain values such as:

- Rear End
- Front-to-Front
- Front-to-Rear
- Angle
- Sideswipe
- Other
- Broadside
- Head On
- Approach Turn

For FARS, man_collname is a likely crash-type field.

Severity and KABCO normalization
--------------------------------
The dashboard can use either a KABCO field or separate person-count fields.

KABCO meaning:

K = Fatal injury
A = Suspected serious injury / incapacitating injury
B = Suspected minor injury / non-incapacitating injury
C = Possible injury / complaint of injury
O = Property damage only / no injury / uninjured

The app attempts to normalize fields like:

- Fatalities -> K person count
- Level A Injuries / Serious Injuries -> A person count
- Level B Injuries / Non-incapacitating Injuries -> B person count
- Level C Injuries / Possible Injuries -> C person count
- Uninjured / No Injury / PDO -> O person count

Crash-level KPI logic
---------------------
The top dashboard KPI cards are intended to show:

- Total crashes
- Fatal crashes
- Fatalities
- Serious injury crashes
- Serious injuries

Important difference:

- Fatalities means number of people killed.
- Fatal crashes means number of unique crashes with at least one fatality.
- Serious injuries means number of people seriously injured.
- Serious injury crashes means number of unique crashes with at least one serious injury.

For example, a dataset may have 19 fatalities but only 15 fatal crashes if some crashes involved more than one fatality.

The app should count fatal crashes using the unique crash ID / case ID when available, not by summing fatalities.

Step 2 - Build Spatial Units
----------------------------
Spatial units depend on the workflow.

Intersection workflow
---------------------
The Intersection workflow builds signalized intersection units.

The general method is:

1. Load or fetch traffic signals.
2. Remove duplicate signals using a default duplicate-distance threshold.
3. Use signal locations and nearby roads to define signalized intersections.
4. Create intersection spatial units.
5. Join crashes to those units.
6. Calculate crash count and crash density.

Signals are required for intersection creation. Only the thresholds are optional.

Intersection output tables should include fields such as:

- Rank
- Spatial unit ID
- Road 1
- Road 2
- Crash count
- Crash density
- KABCO/severity fields when available

Corridor workflow
-----------------
The Corridor workflow builds corridors from signalized routes.

The general method is:

1. Generate or load signals.
2. Assign signals to nearby roads.
3. Group signals by route or road name.
4. Build corridor geometries for valid signalized routes.
5. Allow corridors to be dropped by ID.
6. Store both all generated corridors and filtered/final corridors.
7. Join crashes to corridors.
8. Calculate corridor crash count and crash density.

Corridor output tables should include fields such as:

- Rank
- Corridor ID
- Route name
- Route total length
- Corridor length
- Crash count
- Crash density
- KABCO/severity fields when available

Segment workflow
----------------
The Segment workflow uses road segments as spatial units.

The app should use all selected road segments for segment crash classification and HIN analysis, not only roads inside final corridors.

Segment output tables should include fields such as:

- Rank
- Segment ID
- Route name
- Route total length
- Segment length
- From mile
- To mile
- Crash count
- Crash density
- HIN index when available

FromMile / ToMile generation
----------------------------
The app automatically generates FromMile and ToMile values for roads and segments. Earlier manual direction options were removed to keep the workflow simpler.

Step 3 - Analysis
-----------------
Crash density analysis
----------------------
Crash density is the main analysis result for intersections, corridors, and segments.

General concept:

Crash Density = Crash Count / Exposure Unit

For intersections, the exposure unit is typically the intersection spatial unit.

For corridors and segments, the exposure unit is typically length in miles.

Results are considered ready after crash-density analysis for:

- Intersection
- Corridor
- Segment

Sliding Window / HIN analysis
-----------------------------
Sliding Window / HIN analysis is mainly used in the Segment workflow.

The method creates moving windows along routes, counts crashes in each window, and calculates a HIN priority index.

The HIN table should show one row per high-risk segment/window and include:

- Rank
- SegID or window ID
- Segment/window length
- From mile
- To mile
- Route
- Route total length
- HIN index

If the HIN result is based on sliding windows, the From mile and To mile fields should describe the window mile range, not a separate route mile range.

Route From mile and Route To mile are not needed in the HIN table.

Step 4 - Visualization
----------------------
The Visualization section displays result maps.

Visualization filters are display-only. They should not overwrite the saved result data.

Common map filters include:

- Minimum crash count
- Show all features
- Top N
- Top X percent
- Top X percent of length/network miles

Crash Density Map
-----------------
The Crash Density Map shows spatial units colored by crash density.

Color meaning:

Green = low value
Yellow = moderate value
Orange = high value
Red = highest value

HIN Priority Map
----------------
The HIN Priority Map shows HIN segments/windows by HIN priority index.

Color meaning:

Green = lower priority
Yellow = moderate priority
Orange = high priority
Red = highest priority

Dashboard map layers
--------------------
Dashboard maps are read-only and can include optional context layers, such as:

- Roads
- Road class layer
- Signals
- Crash points
- Corridors
- Generated corridors
- Study boundary

The layer control should stay compact or collapsed so it does not cover the map.

Signals should only appear in exported report maps when the Signals layer is selected.

Manual bounding-box and polygon selection
-----------------------------------------
The manual bounding-box summary and polygon drawing tools have been removed from the stable workflow.

Step 5 - Dashboard, Downloads, and Reports
------------------------------------------
The dashboard is organized around two major groups:

1. Crash patterns
2. Risk patterns / spatial-unit ranking

Crash summary KPI cards
-----------------------
At the top of Crash Insights, the app shows KPI cards such as:

- Total crashes
- Fatal crashes
- Fatalities
- Serious injury crashes
- Serious injuries

These KPI cards should also be available in Dashboard Builder and included in the Word report when selected.

Crash pattern charts
--------------------
Crash Insights can include:

- Crashes by year stacked by KABCO
- Crash type pie/donut chart
- Monthly crash trend by year
- Travel mode severity bubble chart
- Road class by KABCO heatmap when road class filter is enabled
- Crash type by KABCO heatmap
- Crash type and KABCO treemap

Crashes by year stacked by KABCO
--------------------------------
This chart should use:

- X-axis: year
- Y-axis: crash count
- Color/stack: KABCO or normalized severity

K, A, B, C, and O should use distinct colors.

Hover tooltip should show the count for each severity in each year.

Crash type pie/donut chart
--------------------------
This chart shows the share of crashes by crash type.

The app should auto-detect crash type fields when possible. For FARS, man_collname is a likely crash type field.

Monthly crash trend by year
---------------------------
This chart should use:

- X-axis: Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec
- Y-axis: crash count
- One colored line per year

If there is no explicit month field, the app should try to extract month from a crash date field.

Travel mode severity bubble chart
---------------------------------
This chart summarizes pedestrian, bicycle, motorcycle, and motor-vehicle-related crashes by severity.

A recommended layout is:

- X-axis: K, A, B, C, O
- Y-axis: travel mode
- Bubble size: crash count
- Color: travel mode


Crash type by KABCO heatmap
---------------------------
This chart helps show which crash types are associated with more severe outcomes.

Recommended layout:

- Rows: crash type
- Columns: K, A, B, C, O
- Color: crash count

Road class by KABCO heatmap
---------------------------
This chart appears only when the Road Class Filter is enabled and the road-class field is available.

Recommended layout:

- Rows: road class
- Columns: K, A, B, C, O
- Color: crash count

Crash type and KABCO treemap
----------------------------
This chart can show hierarchical crash composition, such as:

Crash type -> KABCO severity

It is useful when there are many crash types.

Risk pattern charts and tables
------------------------------
Risk Insights can include:

- Top spatial units by crash density
- Top spatial units by crash count
- HIN priority table
- High Injury Network summary
- Crash Density Map
- HIN Priority Map

Top spatial units by crash density
----------------------------------
This chart should be sorted highest to lowest.

Recommended axis setup:

- Y-axis: spatial unit ID
- X-axis: crash density

Tooltip should include available context such as:

- Spatial unit ID
- Route name
- From mile
- To mile
- Segment/window length
- Crash count
- Crash density

Top spatial units by crash count
--------------------------------
This chart should be sorted highest to lowest.

Recommended axis setup:

- Y-axis: spatial unit ID
- X-axis: crash count

Tooltip should include route and milepost context when available.

HIN priority table
------------------
The HIN priority result should use a table instead of a confusing stacked bar chart.

Recommended columns:

- Rank
- SegID
- Seg/window length
- From mile
- To mile
- Route
- Route total length
- HIN index

For intersections, extra context columns can include:

- Road 1
- Road 2

For corridors and segments, extra context columns can include:

- Route name
- Route total length
- Spatial unit length

High Injury Network summary
---------------------------
The HIN summary shows how much of the network and how many crashes are captured by the selected high-risk network threshold.

Users can select thresholds such as:

- Top 20 segments/windows
- Top 10 percent of miles
- Top 5 percent of miles
- HIN index >= 75
- HIN index >= 50

The green arrow on the HIN summary cards does not mean a time trend. It means the selected HIN share of analyzed miles or assigned crashes.

For example:

High-risk miles: 2.00 mi
Green arrow: 1.6 percent of analyzed miles

This means the selected high-risk network represents 1.6 percent of the analyzed road mileage.

Downloads and exports
---------------------
The app supports:

- CSV result downloads
- Excel result downloads
- GeoJSON/GIS result downloads when available
- Word report export
- PNG dashboard summary export

Corridor downloads should distinguish between:

1. All generated corridors
2. Filtered/final corridors after dropped corridors are removed

Word report export
------------------
The Word report is intended to include:

- Report generation time using the selected report time zone
- Crash summary KPI numbers
- Selected charts
- Selected tables
- Selected map images

The report should focus on decision-ready outputs, not raw uploaded crash tables.

Report maps
-----------
Report maps should include selected result layers, such as:

- Crash density layer
- HIN priority layer

Context layers should only appear if selected in Dashboard Builder, such as:

- Roads
- Signals
- Corridors
- Study boundary

Signals should not be forced into report maps, because green signal points can be confused with green low-risk crash-density features.

For dense segment maps, report map segment line width should be thin enough to see the network clearly.


Clear history / start over
--------------------------
The app includes a Clear history / Start over button near the workflow selector.

This should clear session state so the user can restart without old analysis results, maps, or uploads interfering with the new run.

Known limitations
-----------------
Direct click-to-delete corridors from the map
---------------------------------------------
The stable app uses ID-based corridor deletion.

Directly clicking a corridor on a Folium map and deleting it would require custom JavaScript callbacks. That is possible but less stable in regular Streamlit/Folium.

Static map export
-----------------
Static map images in Word reports are generated from selected layers. They may not exactly match the interactive Folium map because web basemap tiles and matplotlib/static rendering behave differently.


Shapefile ZIP upload fails
--------------------------
Make sure the ZIP contains at least:

.shp
.shx
.dbf
.prj

If possible, use GeoPackage .gpkg, which is often more reliable than shapefile ZIP.

Suggested future improvements
-----------------------------
Possible future improvements include:

- More stable map screenshot capture from the exact interactive Folium view.
- Click chart bar to highlight a feature on the map.
- Direct map-based corridor deletion.
- Saved dashboard templates.
- User-defined report templates.
- Standalone HTML dashboard export with embedded charts and maps.
