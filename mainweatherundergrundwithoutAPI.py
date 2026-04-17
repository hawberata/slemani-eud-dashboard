import streamlit as st
import calendar
import numpy as np
import pandas as pd
import folium
import platform
import matplotlib.pyplot as plt
from datetime import datetime
from io import StringIO
from folium.plugins import Draw
from streamlit_folium import st_folium
from scipy.spatial.distance import cdist
from shapely.geometry import Polygon as ShapelyPolygon, Point, MultiPoint, box
from shapely.ops import voronoi_diagram

# --- SCRAPING IMPORTS ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

# ==========================================
# --- INITIAL STATION LIST ---
# ==========================================
if 'station_list' not in st.session_state:
    st.session_state.station_list = [
        {"lon": 45.48, "lat": 35.55, "id": "IKANIS1", "name": "Hawber Station"},
        {"lon": 45.37, "lat": 35.58, "id": "IQALIA1", "name": "UOS-new campus"},
        {"lon": 45.36, "lat": 35.54, "id": "I90583621", "name": "UOS-Bakrajo"},
        {"lon": 45.44, "lat": 35.57, "id": "I90583618", "name": "UOS-oldcampus"}
    ]

# --- HELPER: Generate a list of (Year, Month) tuples between two dates ---
def get_month_year_range(start_year, start_month, end_year, end_month):
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    start_date = datetime(start_year, start_month, 1)
    end_date = datetime(end_year, end_month, 1)
    
    months_to_scrape = []
    
    if start_date > end_date:
        return [] # Invalid range
        
    curr_y, curr_m = start_year, start_month
    while datetime(curr_y, curr_m, 1) <= end_date:
        # Stop if we hit a future month that hasn't happened yet
        if curr_y > current_year or (curr_y == current_year and curr_m > current_month):
            break 
            
        months_to_scrape.append((curr_y, curr_m))
        
        curr_m += 1
        if curr_m > 12:
            curr_m = 1
            curr_y += 1
            
    return months_to_scrape

@st.cache_data(show_spinner=False)
def scrape_weather_data(months_to_scrape, station_data):
    """Scrapes data for a specific list of (Year, Month) tuples."""
    results = []
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.page_load_strategy = 'eager'

    if platform.system() == "Linux":
        driver_service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
    else:
        driver_service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=driver_service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    for s in station_data:
        accumulated_mm = 0.0
        valid_months_found = 0

        for y, m in months_to_scrape:
            _, num_days = calendar.monthrange(y, m)
            url = f"https://www.wunderground.com/dashboard/pws/{s['id']}/graph/{y}-{m:02d}-{num_days:02d}/{y}-{m:02d}-{num_days:02d}/monthly"

            try:
                driver.get(url)
                WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".summary-table, table")))
                html = driver.page_source
                tables = pd.read_html(StringIO(html))

                for df in tables:
                    df_str = df.astype(str)
                    if df_str.apply(lambda row: row.astype(str).str.contains('Precipitation', case=False).any(), axis=1).any():
                        precip_row = df[df.apply(lambda row: row.astype(str).str.contains('Precipitation', case=False).any(), axis=1)]
                        if not precip_row.empty:
                            val_str = str(precip_row.iloc[0].values[1])
                            clean_val = ''.join(c for c in val_str if c.isdigit() or c == '.')
                            if clean_val:
                                val = float(clean_val)
                                val_mm = val * 25.4 if 'in' in val_str.lower() else val
                                accumulated_mm += val_mm
                                valid_months_found += 1
                                break
            except Exception:
                pass # Skip offline months

        if valid_months_found == 0:
            final_total = None
        else:
            final_total = accumulated_mm

        results.append([s['lon'], s['lat'], final_total, s['name']])

    driver.quit()
    return np.array(results, dtype=object)

# ==========================================
# --- UI Layout ---
# ==========================================
st.set_page_config(page_title="Slemani EUD Dashboard", layout="wide")
st.title("🗺️ Equivalent Uniform Depth (EUD) for Slemani")
st.markdown("##### **Developed by: Hawber Ata**")

with st.sidebar:
    st.header("⚙️ Station Settings")
    with st.expander("Add/Manage Stations"):
        new_name = st.text_input("Station Name")
        new_id = st.text_input("WU Station ID (e.g. IKANIS1)")
        c1, c2 = st.columns(2)
        new_lat = c1.number_input("Latitude", format="%.5f", value=35.5)
        new_lon = c2.number_input("Longitude", format="%.5f", value=45.4)

        if st.button("➕ Add Station to List"):
            if new_id and new_name:
                st.session_state.station_list.append({"lon": new_lon, "lat": new_lat, "id": new_id, "name": new_name})
                st.rerun()

        if st.button("🗑️ Reset to Default (4 Stations)"):
            del st.session_state.station_list
            st.rerun()

    st.divider()
    st.header("Report Parameters")
    
    # --- ADDED: Custom Season UI ---
    time_period = st.radio("Time Period", ["Single Month", "Custom Season / Date Range"])
    
    months_to_scrape = [] # Will hold our list of targets
    
    if time_period == "Single Month":
        selected_year = st.selectbox("Select Year", [2026, 2025, 2024, 2023, 2022], index=0)
        selected_month = st.selectbox("Select Month", list(range(1, 13)), index=2, format_func=lambda x: calendar.month_name[x])
        months_to_scrape = [(selected_year, selected_month)]
    else:
        st.info("💡 **Custom Range:** Perfect for a Hydrological Year (e.g., Oct 2025 to jun 2026).")
        colA, colB = st.columns(2)
        with colA:
            st.write("**Start Date**")
            start_month = st.selectbox("Start Month", list(range(1, 13)), index=8, format_func=lambda x: calendar.month_name[x]) # Default Sept
            start_year = st.selectbox("Start Year", [2026, 2025, 2024, 2023, 2022], index=1)
        with colB:
            st.write("**End Date**")
            end_month = st.selectbox("End Month", list(range(1, 13)), index=4, format_func=lambda x: calendar.month_name[x]) # Default May
            end_year = st.selectbox("End Year", [2026, 2025, 2024, 2023, 2022], index=0)
            
        months_to_scrape = get_month_year_range(start_year, start_month, end_year, end_month)
        
        if not months_to_scrape and (start_year > end_year or (start_year == end_year and start_month > end_month)):
            st.error("⚠️ Start date must be before End date!")
        elif not months_to_scrape:
            st.warning("⚠️ Selected dates are in the future.")

    calc_method = st.radio("Calculation Method", ["Arithmetic Mean", "Thiessen Polygons (Geographic)", "Isohyetal (IDW Interpolation)"], index=1)
    show_zones = st.checkbox("Show Station Influence Zones", value=True)

# Process ALL Stations for Map Display
all_coords = np.array([[s['lon'], s['lat']] for s in st.session_state.station_list])
all_names = [s['name'] for s in st.session_state.station_list]

# --- Setup Map ---
map_state = st.session_state.get("catchment_map", {})
active_drawing = map_state.get("last_active_drawing")

if active_drawing and active_drawing["geometry"]["type"] == "Polygon":
    bounding_shape = ShapelyPolygon(active_drawing["geometry"]["coordinates"][0])
else:
    margin = 0.05
    bounding_shape = box(all_coords[:, 0].min() - margin, all_coords[:, 1].min() - margin,
                         all_coords[:, 0].max() + margin, all_coords[:, 1].max() + margin)

m = folium.Map(location=[35.56, 45.41], zoom_start=12, tiles="CartoDB positron")

if show_zones and len(all_coords) >= 2:
    large_bbox = box(all_coords[:, 0].min() - 2, all_coords[:, 1].min() - 2, all_coords[:, 0].max() + 2,
                     all_coords[:, 1].max() + 2)
    points = MultiPoint([Point(x, y) for x, y in all_coords])
    voronoi_polys = voronoi_diagram(points, envelope=large_bbox)
    colors = ['#ff9999', '#66b3ff', '#99ff99', '#ffcc99', '#c2c2f0', '#ffb3e6', '#c4e17f']

    for poly in voronoi_polys.geoms:
        clipped_poly = poly.intersection(bounding_shape)
        if not clipped_poly.is_empty and clipped_poly.geom_type == 'Polygon':
            distances = [clipped_poly.centroid.distance(Point(x, y)) for x, y in all_coords]
            idx = np.argmin(distances) % len(colors)
            folium.Polygon(locations=[(y, x) for x, y in clipped_poly.exterior.coords], color="black", weight=1,
                           fill=True, fill_color=colors[idx], fill_opacity=0.3).add_to(m)

for s in st.session_state.station_list:
    folium.Marker([s['lat'], s['lon']], tooltip=s['name'], icon=folium.Icon(color="darkblue", icon="cloud")).add_to(m)

draw = Draw(
    draw_options={'polyline': False, 'rectangle': False, 'circle': False, 'marker': False, 'circlemarker': False})
m.add_child(draw)

st.write("### 1. Define Catchment Area")
st_folium(m, width=1000, height=500, key="catchment_map", returned_objects=["last_active_drawing"])

st.divider()
st.write("### 2. Precipitation Results")

# Disable button if range is invalid
calc_disabled = len(months_to_scrape) == 0

if st.button("🧮 Calculate EUD", type="primary", use_container_width=True, disabled=calc_disabled):
    
    loading_msg = f"Extracting {len(months_to_scrape)} months of data for all stations (this may take a few minutes)..."
    
    with st.spinner(loading_msg):
        data = scrape_weather_data(months_to_scrape, st.session_state.station_list)

        valid_data = [row for row in data if row[2] is not None]

        # Display the metrics
        cols = st.columns(len(data))
        for i, row in enumerate(data):
            if row[2] is not None:
                cols[i].metric(label=row[3], value=f"{row[2]:.2f} mm")
            else:
                cols[i].metric(label=row[3], value="Offline", delta="No data found", delta_color="off")

        # If ALL stations are offline, stop the math!
        if len(valid_data) == 0:
            st.error("❌ All stations are offline or missing data in this timeframe. Cannot calculate EUD.")
        else:
            active_precip = np.array([row[2] for row in valid_data], dtype=float)
            active_coords = np.array([[row[0], row[1]] for row in valid_data], dtype=float)
            active_names = [row[3] for row in valid_data]

            if len(valid_data) < len(data):
                st.warning(
                    f"⚠️ Warning: {len(data) - len(valid_data)} station(s) were offline. The network has automatically re-balanced using only active stations.")

            if calc_method == "Arithmetic Mean":
                st.success(f"**Final Arithmetic Mean EUD:** {np.mean(active_precip):.2f} mm")

            elif calc_method == "Thiessen Polygons (Geographic)":
                if active_drawing:
                    min_lon, min_lat, max_lon, max_lat = bounding_shape.bounds
                    grid_lon, grid_lat = np.meshgrid(np.linspace(min_lon, max_lon, 150),
                                                     np.linspace(min_lat, max_lat, 150))
                    grid_points = np.c_[grid_lon.ravel(), grid_lat.ravel()]
                    inside_points = np.array([pt for pt in grid_points if bounding_shape.contains(Point(pt))])

                    if len(inside_points) > 0:
                        closest_station = np.argmin(cdist(inside_points, active_coords), axis=1)
                        thiessen_eud = sum(
                            (np.sum(closest_station == i) / len(inside_points)) * active_precip[i] for i in
                            range(len(active_coords)))

                        st.write("#### Active Area Distribution within Catchment")
                        area_cols = st.columns(len(active_coords))
                        for i in range(len(active_coords)):
                            area_fraction = np.sum(closest_station == i) / len(inside_points)
                            area_cols[i].caption(f"**{active_names[i]}:** {area_fraction * 100:.1f}%")

                        st.success(f"**Final Area-Weighted Thiessen EUD:** {thiessen_eud:.2f} mm")
                    else:
                        st.warning("The drawn polygon is too small. Please draw a larger boundary.")
                else:
                    st.warning("⚠️ Please draw a polygon on the map first, then click Calculate.")
                    
            elif calc_method == "Isohyetal (IDW Interpolation)":
                if active_drawing:
                    min_lon, min_lat, max_lon, max_lat = bounding_shape.bounds
                    grid_lon, grid_lat = np.meshgrid(np.linspace(min_lon, max_lon, 150),
                                                     np.linspace(min_lat, max_lat, 150))
                    grid_points = np.c_[grid_lon.ravel(), grid_lat.ravel()]
                    
                    mask = np.array([bounding_shape.contains(Point(pt)) for pt in grid_points])
                    inside_points = grid_points[mask]

                    if len(inside_points) > 0:
                        dist_matrix = cdist(inside_points, active_coords)
                        dist_matrix = np.where(dist_matrix == 0, 1e-10, dist_matrix)
                        weights = 1.0 / (dist_matrix**2)
                        interpolated_values = np.sum(weights * active_precip, axis=1) / np.sum(weights, axis=1)
                        
                        isohyetal_eud = np.mean(interpolated_values)
                        st.success(f"**Final Area-Weighted Isohyetal (IDW) EUD:** {isohyetal_eud:.2f} mm")
                        
                        st.write("#### Isohyetal Contour Map")
                        
                        fig, ax = plt.subplots(figsize=(8, 5))
                        full_grid = np.full(grid_lon.shape, np.nan)
                        full_grid.ravel()[mask] = interpolated_values
                        
                        cp = ax.contourf(grid_lon, grid_lat, full_grid, cmap='Blues', levels=10, alpha=0.8)
                        plt.colorbar(cp, label='Precipitation (mm)')
                        
                        x, y = bounding_shape.exterior.xy
                        ax.plot(x, y, color='#333333', linewidth=2, label='Catchment Boundary')
                        
                        ax.scatter(active_coords[:,0], active_coords[:,1], color='red', s=40, label='Stations', zorder=5)
                        for i, name in enumerate(active_names):
                            ax.annotate(name, (active_coords[i,0], active_coords[i,1]), 
                                        textcoords="offset points", xytext=(5,5), ha='left', fontsize=8)
                            
                        ax.set_xlabel("Longitude")
                        ax.set_ylabel("Latitude")
                        ax.legend()
                        
                        st.pyplot(fig)
                    else:
                        st.warning("The drawn polygon is too small. Please draw a larger boundary.")
                else:
                    st.warning("⚠️ Please draw a polygon on the map first, then click Calculate.")
