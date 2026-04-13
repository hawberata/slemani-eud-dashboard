import streamlit as st
import requests
import calendar
import numpy as np
import folium
import re  # <--- NEW: Required for the security bypass
from folium.plugins import Draw
from streamlit_folium import st_folium
from scipy.spatial.distance import cdist
from shapely.geometry import Polygon as ShapelyPolygon, Point, MultiPoint, box
from shapely.ops import voronoi_diagram

# ==========================================
# --- Configuration & Data (ECOWIT API) ---
# ==========================================
# Your Ecowit Keys
ECOWIT_APP_KEY = "3A97A4F04494D4E5EADEB20300175203"
ECOWIT_API_KEY = "075b743d-e408-4df3-b9ef-fde8e71b36fb"

# Your exact Station MAC Addresses
stations = [
    [45.48, 35.55, "30:83:98:A5:F0:12", "Hawber Station"],
    [45.37, 35.58, "F8:B3:B7:8E:0C:D7", "UOS-new campus"],
    [45.36, 35.54, "F8:B3:B7:8E:23:F5", "UOS-Bakrajo"],
    [45.44, 35.57, "F8:B3:B7:8E:9B:23", "UOS-oldcampus"]
]


@st.cache_data(show_spinner=False)
def fetch_monthly_data(year, month):
    """Fetches real daily precipitation from Ecowit API, bypassing JS challenges."""
    _, num_days = calendar.monthrange(year, month)

    # Format the start and end dates for the Ecowit API (YYYY-MM-DD HH:MM:SS)
    start_date = f"{year}-{month:02d}-01 00:00:00"
    end_date = f"{year}-{month:02d}-{num_days:02d} 23:59:59"

    results = []
    error_shown = False

    for lon, lat, mac_address, name in stations:
        monthly_total_mm = 0.0

        # The official Ecowit API endpoint for historical data
        url = "https://api.ecowit.net/api/v3/device/history"

        # We ask for 'rainfall' on a '1day' cycle for the whole month at once
        params = {
            "application_key": ECOWIT_APP_KEY,
            "api_key": ECOWIT_API_KEY,
            "mac": mac_address,
            "call_back": "rainfall",
            "cycle_type": "1day",
            "start_date": start_date,
            "end_date": end_date
        }

        # Disguise the script and demand JSON data
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*"
        }

        try:
            # Make the initial request
            response = requests.get(url, params=params, headers=headers, timeout=15)

            # --- THE JAVASCRIPT CHALLENGE BYPASS ---
            # If the server responds with the HTML JavaScript redirect trap...
            if "window.location.replace" in response.text:
                # Extract the exact secure URL containing the generated 'js' and 'sid' tokens
                match = re.search(r"window\.location\.replace\(['\"]([^'\"]+)['\"]\)", response.text)
                if match:
                    redirect_url = match.group(1)

                    # Some firewalls encode the & symbol as &amp; in the string, we need to fix that
                    redirect_url = redirect_url.replace("&amp;", "&")

                    # Follow the redirect! (We drop 'params' because they are baked into the new URL)
                    response = requests.get(redirect_url, headers=headers, timeout=15)

            # --- PROCESS THE FINAL DATA ---
            if response.status_code == 200:
                try:
                    # Attempt to read the JSON response
                    api_data = response.json()

                    # Ecowit returns 'code': 0 when the request is successful
                    if api_data.get("code") == 0:
                        try:
                            # Ecowit stores daily rain under: data -> rainfall -> daily -> list
                            rain_data_list = api_data["data"]["rainfall"]["daily"]["list"]

                            # Loop through the days and add up the totals
                            for day_key, value in rain_data_list.items():
                                if value is not None:
                                    monthly_total_mm += float(value)
                        except KeyError:
                            # If the station recorded strictly zero rain for the month
                            pass

                    # If Ecowit API rejects the keys
                    elif api_data.get("code") == 40001 and not error_shown:
                        st.error("🚨 Ecowit API Error: Invalid API Key or Application Key.")
                        error_shown = True

                except ValueError:
                    # IF IT STILL FAILS, PRINT THE RAW TEXT
                    if not error_shown:
                        st.error(
                            f"🚨 Ecowit returned a blank or broken page for {name}. Raw response: '{response.text[:200]}...'")
                        error_shown = True

            else:
                if not error_shown:
                    st.error(f"🚨 Server Error {response.status_code}: {response.text[:200]}")
                    error_shown = True

        except Exception as e:
            if not error_shown:
                st.error(f"🚨 Network Connection Error: {e}")
                error_shown = True

        results.append([lon, lat, monthly_total_mm, name])

    return np.array(results, dtype=object)


# ==========================================
# --- UI Layout ---
# ==========================================
st.set_page_config(page_title="Slemani EUD Dashboard", layout="wide")

st.title("🗺️ Equivalent Uniform Depth (EUD) for Slemani")
st.markdown("##### **Developed by: Hawber Ata**")
st.markdown("Draw your catchment boundary on the map, then click Calculate to compute the area-weighted rainfall.")

# Sidebar
with st.sidebar:
    st.header("Report Parameters")
    selected_year = st.selectbox("Select Year", [2026, 2025, 2024])
    selected_month = st.selectbox("Select Month", list(range(1, 13)), format_func=lambda x: calendar.month_name[x])
    calc_method = st.radio("Calculation Method", ["Arithmetic Mean", "Thiessen Polygons (Geographic)"])

    st.divider()
    show_zones = st.checkbox("Show Station Influence Zones", value=True,
                             help="Displays the Thiessen boundaries visually clipped to your drawing.")

# --- Setup Map and Geometry ---
coords = np.array([s[:2] for s in stations], dtype=float)
names = [s[3] for s in stations]

# Extract User's Drawn Boundary from Session State
map_state = st.session_state.get("catchment_map", {})
active_drawing = map_state.get("last_active_drawing")

# Determine the bounding shape
if active_drawing is not None and active_drawing["geometry"]["type"] == "Polygon":
    drawn_coords = active_drawing["geometry"]["coordinates"][0]
    bounding_shape = ShapelyPolygon(drawn_coords)
else:
    # Default rectangular box if nothing is drawn yet
    margin = 0.04
    min_lon, max_lon = coords[:, 0].min() - margin, coords[:, 0].max() + margin
    min_lat, max_lat = coords[:, 1].min() - margin, coords[:, 1].max() + margin
    bounding_shape = box(min_lon, min_lat, max_lon, max_lat)

# Initialize the Map centered on Slemani
m = folium.Map(location=[35.56, 45.41], zoom_start=12, tiles="CartoDB positron")

# Generate and Draw DYNAMICALLY CLIPPED Thiessen Influence Zones
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

# Add Station Markers
for i in range(len(coords)):
    folium.Marker(
        location=[coords[i, 1], coords[i, 0]],
        popup=names[i],
        tooltip=names[i],
        icon=folium.Icon(color="darkblue", icon="cloud")
    ).add_to(m)

# Add Drawing Tools
draw = Draw(
    draw_options={'polyline': False, 'rectangle': False, 'circle': False, 'marker': False, 'circlemarker': False},
    edit_options={'edit': True, 'remove': True}
)
m.add_child(draw)

# Render Map in Streamlit
st.write("### 1. Define Catchment Area")
st.info("Use the polygon tool to draw your catchment boundary. The math will not run until you click Calculate below.")

map_output = st_folium(
    m,
    width=1000,
    height=500,
    key="catchment_map",
    returned_objects=["last_active_drawing"]
)

st.divider()

st.write("### 2. Precipitation Results")

# ==========================================
# --- Manual Calculation Block ---
# ==========================================
if st.button("🧮 Calculate EUD", type="primary", use_container_width=True):

    with st.spinner(f"Pulling Live Ecowit API Data for {calendar.month_name[selected_month]} {selected_year}..."):
        # Fetch the live API data
        data = fetch_monthly_data(selected_year, selected_month)
        precip = np.array(data[:, 2], dtype=float)

        # Show the raw station values
        cols = st.columns(4)
        for i, col in enumerate(cols):
            col.metric(label=names[i], value=f"{precip[i]:.2f} mm")

        if calc_method == "Arithmetic Mean":
            arithmetic_eud = np.mean(precip)
            st.success(f"**Final Arithmetic Mean EUD:** {arithmetic_eud:.2f} mm")

        elif calc_method == "Thiessen Polygons (Geographic)":
            if active_drawing is not None:
                with st.spinner("Calculating area weights based on your drawn boundary..."):

                    min_lon, min_lat, max_lon, max_lat = bounding_shape.bounds
                    grid_lon, grid_lat = np.meshgrid(
                        np.linspace(min_lon, max_lon, 150),
                        np.linspace(min_lat, max_lat, 150)
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
                        st.warning(
                            "The drawn polygon is too small or contains no data points. Please draw a larger boundary.")
            else:
                st.warning("⚠️ Please draw a polygon on the map first, then click Calculate.")
else:
    st.caption("Waiting for calculation... Draw your boundary and click the button above.")