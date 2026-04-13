import streamlit as st
import calendar
import numpy as np
import pandas as pd
import folium
import platform  # <-- NEW: Allows Python to check if you are on Windows or Linux
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
from bs4 import BeautifulSoup

# ==========================================
# --- Configuration & Data (NO APIs NEEDED) ---
# ==========================================
# Using the original Weather Underground Station IDs
stations = [
    [45.48, 35.55, "IKANIS1", "Hawber Station"],
    [45.37, 35.58, "IQALIA1", "UOS-new campus"],
    [45.36, 35.54, "I90583621", "UOS-Bakrajo"],
    [45.44, 35.57, "I90583618", "UOS-oldcampus"]
]


@st.cache_data(show_spinner=False)
def scrape_monthly_data(year, month):
    """Uses a high-speed invisible Chrome browser to scrape WU graph summaries."""
    _, num_days = calendar.monthrange(year, month)

    results = []

    # Setup the invisible Chrome browser
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.page_load_strategy = 'eager'

    # --- SMART OS DETECTION ---
    # Automatically chooses the right driver based on your current machine
    if platform.system() == "Linux":
        # If running on Streamlit Cloud
        driver_service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
    else:
        # If running locally on your Windows computer
        driver_service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=driver_service, options=chrome_options)

    for lon, lat, st_id, name in stations:
        monthly_total_mm = 0.0

        # Target the high-speed Graph summary URL
        url = f"https://www.wunderground.com/dashboard/pws/{st_id}/graph/{year}-{month:02d}-{num_days:02d}/{year}-{month:02d}-{num_days:02d}/monthly"

        try:
            driver.get(url)

            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".summary-table, table, .dashboard__summary"))
            )

            html = driver.page_source
            soup = BeautifulSoup(html, 'lxml')

            tables = pd.read_html(str(soup))

            for df in tables:
                df_str = df.astype(str)

                if df_str.apply(lambda row: row.astype(str).str.contains('Precipitation', case=False).any(),
                                axis=1).any():
                    precip_row = df[
                        df.apply(lambda row: row.astype(str).str.contains('Precipitation', case=False).any(), axis=1)]

                    if not precip_row.empty:
                        val_str = str(precip_row.iloc[0].values[1])
                        clean_val = ''.join(c for c in val_str if c.isdigit() or c == '.')

                        if clean_val:
                            val = float(clean_val)
                            if 'in' in val_str.lower() or val < 30.0:
                                monthly_total_mm = val * 25.4
                            else:
                                monthly_total_mm = val
                            break

        except Exception as e:
            st.warning(f"⚠️ Could not scrape {name}: The station may be offline or the page timed out.")

        results.append([lon, lat, monthly_total_mm, name])

    driver.quit()

    return np.array(results, dtype=object)


# ==========================================
# --- UI Layout ---
# ==========================================
st.set_page_config(page_title="Slemani EUD Dashboard", layout="wide")

st.title("🗺️ Equivalent Uniform Depth (EUD) for Slemani")
st.markdown("##### **Developed by: Hawber Ata**")
st.markdown("Draw your catchment boundary on the map, then click Calculate to compute the area-weighted rainfall.")

with st.sidebar:
    st.header("Report Parameters")
    selected_year = st.selectbox("Select Year", [2026, 2025, 2024])
    selected_month = st.selectbox("Select Month", list(range(1, 13)), format_func=lambda x: calendar.month_name[x])
    calc_method = st.radio("Calculation Method", ["Arithmetic Mean", "Thiessen Polygons (Geographic)"])
    st.divider()
    show_zones = st.checkbox("Show Station Influence Zones", value=True)

# --- Setup Map and Geometry ---
coords = np.array([s[:2] for s in stations], dtype=float)
names = [s[3] for s in stations]

map_state = st.session_state.get("catchment_map", {})
active_drawing = map_state.get("last_active_drawing")

if active_drawing is not None and active_drawing["geometry"]["type"] == "Polygon":
    drawn_coords = active_drawing["geometry"]["coordinates"][0]
    bounding_shape = ShapelyPolygon(drawn_coords)
else:
    margin = 0.04
    min_lon, max_lon = coords[:, 0].min() - margin, coords[:, 0].max() + margin
    min_lat, max_lat = coords[:, 1].min() - margin, coords[:, 1].max() + margin
    bounding_shape = box(min_lon, min_lat, max_lon, max_lat)

m = folium.Map(location=[35.56, 45.41], zoom_start=12, tiles="CartoDB positron")

if show_zones:
    large_bbox = box(coords[:, 0].min() - 1, coords[:, 1].min() - 1, coords[:, 0].max() + 1, coords[:, 1].max() + 1)
    points = MultiPoint([Point(lon, lat) for lon, lat in coords])
    voronoi_polys = voronoi_diagram(points, envelope=large_bbox)

    colors = ['#ff9999', '#66b3ff', '#99ff99', '#ffcc99']

    for poly in voronoi_polys.geoms:
        clipped_poly = poly.intersection(bounding_shape)
        if not clipped_poly.is_empty and clipped_poly.geom_type == 'Polygon':
            centroid = clipped_poly.centroid
            distances = [centroid.distance(Point(lon, lat)) for lon, lat in coords]
            closest_idx = np.argmin(distances)

            folium_coords = [(y, x) for x, y in clipped_poly.exterior.coords]
            folium.Polygon(
                locations=folium_coords, color="black", weight=2,
                fill=True, fill_color=colors[closest_idx], fill_opacity=0.4,
                tooltip=f"{names[closest_idx]} Zone"
            ).add_to(m)

for i in range(len(coords)):
    folium.Marker(
        location=[coords[i, 1], coords[i, 0]], popup=names[i], tooltip=names[i],
        icon=folium.Icon(color="darkblue", icon="cloud")
    ).add_to(m)

draw = Draw(
    draw_options={'polyline': False, 'rectangle': False, 'circle': False, 'marker': False, 'circlemarker': False},
    edit_options={'edit': True, 'remove': True}
)
m.add_child(draw)

st.write("### 1. Define Catchment Area")
st.info("Use the polygon tool to draw your catchment boundary. The scraper will run when you click Calculate.")

map_output = st_folium(m, width=1000, height=500, key="catchment_map", returned_objects=["last_active_drawing"])

st.divider()
st.write("### 2. Precipitation Results")

# ==========================================
# --- Calculation & Scraping Block ---
# ==========================================
if st.button("🧮 Calculate EUD", type="primary", use_container_width=True):

    with st.spinner(
            f"Booting Web Scraper... Extracting data from Weather Underground for {calendar.month_name[selected_month]} {selected_year} (This takes ~30 seconds)..."):
        data = scrape_monthly_data(selected_year, selected_month)
        precip = np.array(data[:, 2], dtype=float)

        cols = st.columns(4)
        for i, col in enumerate(cols):
            col.metric(label=names[i], value=f"{precip[i]:.2f} mm")

        if calc_method == "Arithmetic Mean":
            arithmetic_eud = np.mean(precip)
            st.success(f"**Final Arithmetic Mean EUD:** {arithmetic_eud:.2f} mm")

        elif calc_method == "Thiessen Polygons (Geographic)":
            if active_drawing is not None:
                with st.spinner("Calculating area weights..."):
                    min_lon, min_lat, max_lon, max_lat = bounding_shape.bounds
                    grid_lon, grid_lat = np.meshgrid(
                        np.linspace(min_lon, max_lon, 150), np.linspace(min_lat, max_lat, 150)
                    )
                    grid_points = np.c_[grid_lon.ravel(), grid_lat.ravel()]
                    inside_points = [pt for pt in grid_points if bounding_shape.contains(Point(pt))]
                    inside_points = np.array(inside_points)

                    if len(inside_points) > 0:
                        distances = cdist(inside_points, coords)
                        closest_station = np.argmin(distances, axis=1)

                        thiessen_eud = 0.0
                        st.write("#### Area Distribution within Catchment")
                        area_cols = st.columns(4)

                        for i in range(len(coords)):
                            area_fraction = np.sum(closest_station == i) / len(inside_points)
                            thiessen_eud += area_fraction * precip[i]
                            area_cols[i].caption(f"**{names[i]}:** {area_fraction * 100:.1f}%")

                        st.success(f"**Final Area-Weighted Thiessen EUD for Slemani:** {thiessen_eud:.2f} mm")
                    else:
                        st.warning("The drawn polygon is too small. Please draw a larger boundary.")
            else:
                st.warning("⚠️ Please draw a polygon on the map first, then click Calculate.")
else:
    st.caption("Waiting for calculation... Draw your boundary and click the button above.")