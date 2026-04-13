import streamlit as st
import requests
import calendar
import numpy as np
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from scipy.spatial.distance import cdist
from shapely.geometry import Polygon as ShapelyPolygon, Point, MultiPoint, box
from shapely.ops import voronoi_diagram
# to run use this  streamlit run mainweatherundergrund.py
# --- Configuration & Data ---
# REPLACE THIS WITH YOUR REAL WEATHER UNDERGROUND API KEY
API_KEY = "7ac9b77742c447ff89b77742c4d7ff3f"

stations = [
    [45.48, 35.55, "IKANIS1", "Hawber Station"],
    [45.37, 35.58, "IQALIA1", "UOS-new campus"],
    [45.36, 35.54, "I90583621", "UOS-Bakrajo"],
    [45.44, 35.57, "I90583618", "UOS-oldcampus"]
]


@st.cache_data(show_spinner=False)
def fetch_monthly_data(year, month):
    """Fetches real daily precipitation from WU API with error tracking."""
    _, num_days = calendar.monthrange(year, month)
    results = []

    # We use this flag so the UI doesn't flood with 120 identical error messages
    error_shown = False

    for lon, lat, st_id, name in stations:
        monthly_total_mm = 0.0

        for day in range(1, num_days + 1):
            date_str = f"{year}{month:02d}{day:02d}"
            url = f"https://api.weather.com/v2/pws/history/daily?stationId={st_id}&format=json&units=m&date={date_str}&apiKey={API_KEY}"

            try:
                response = requests.get(url, timeout=10)

                # HTTP 200 means Success!
                if response.status_code == 200:
                    api_data = response.json()
                    if 'observations' in api_data and len(api_data['observations']) > 0:
                        daily_precip = api_data['observations'][0]['metric']['precipTotal']
                        if daily_precip is not None:
                            monthly_total_mm += daily_precip

                # HTTP 204 means the station was offline that day (No Content)
                elif response.status_code == 204:
                    pass

                    # HTTP 401 means the API Key is rejected
                elif response.status_code == 401 and not error_shown:
                    st.error(
                        "🚨 API Error 401: Unauthorized. Check that your API key is correct and has access to historical data.")
                    error_shown = True

                # HTTP 403 means you hit your limit
                elif response.status_code == 403 and not error_shown:
                    st.error("🚨 API Error 403: Forbidden. You may have hit your daily API limit.")
                    error_shown = True

                # Catch any other HTTP errors
                elif response.status_code not in [200, 204] and not error_shown:
                    st.error(
                        f"🚨 API Error {response.status_code}: The Weather Underground servers rejected the request.")
                    error_shown = True

            except Exception as e:
                if not error_shown:
                    st.error(f"🚨 Code/Connection Error: {e}")
                    error_shown = True

        results.append([lon, lat, monthly_total_mm, name])

    return np.array(results, dtype=object)


# --- UI Layout ---
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
# We initialize empty arrays just for the map drawing (the real API fetch happens on button click)
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

# Initialize the Map
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

# --- Manual Calculation Block ---
if st.button("🧮 Calculate EUD", type="primary", use_container_width=True):

    with st.spinner(f"Pulling Live API Data for {calendar.month_name[selected_month]} {selected_year}..."):
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