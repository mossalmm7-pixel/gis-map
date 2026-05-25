import streamlit as st
import numpy as np
import rasterio
from pyproj import Transformer
import plotly.graph_objects as go
import base64
from io import BytesIO
from PIL import Image
import simplekml

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(layout="wide")
st.title("🗺️ ETM MAPS READER ")

# =========================================================
# STATE
# =========================================================
if "points_etm" not in st.session_state:
    st.session_state.points_etm = []

if "submitted" not in st.session_state:
    st.session_state.submitted = False

if "map_number" not in st.session_state:
    st.session_state.map_number = None

if "area_m2" not in st.session_state:
    st.session_state.area_m2 = None

if "view_mode" not in st.session_state:
    st.session_state.view_mode = "ETM"

# Transformers
wgs_to_etm = Transformer.from_crs("EPSG:4326", "EPSG:22992", always_xy=True)
etm_to_wgs = Transformer.from_crs("EPSG:22992", "EPSG:4326", always_xy=True)

# =========================================================
# HELPERS
# =========================================================
def compute_map_number(xs, ys):
    cx = np.mean(xs)
    cy = np.mean(ys)
    return f"{int(cy/1000)}/{int(cx/1500)*1.5}"

def polygon_area(x, y):
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))

# =========================================================
# SIDEBAR
# =========================================================
st.sidebar.header("Control Panel")

# ---------------- ADD POINT ----------------
st.sidebar.subheader("➕ Add Point")

mode = st.sidebar.selectbox(
    "Input Mode",
    ["WGS84 → ETM", "ETM → ETM (direct)"]
)

x_in = st.sidebar.text_input("X")
y_in = st.sidebar.text_input("Y")

if st.sidebar.button("➕ Add Point"):
    try:
        x = float(x_in)
        y = float(y_in)

        if mode == "WGS84 → ETM":
            x2, y2 = wgs_to_etm.transform(x, y)
        else:
            x2, y2 = x, y

        st.session_state.points_etm.append((x2, y2))
        st.sidebar.success(f"Added: {x2:.2f}, {y2:.2f}")

    except:
        st.sidebar.error("Invalid input")

# ---------------- SUBMIT ----------------
if st.sidebar.button("✅ Submit Points"):
    if len(st.session_state.points_etm) < 3:
        st.sidebar.error("Need at least 3 points")
    else:
        xs = np.array([p[0] for p in st.session_state.points_etm])
        ys = np.array([p[1] for p in st.session_state.points_etm])

        st.session_state.map_number = compute_map_number(xs, ys)
        st.session_state.area_m2 = polygon_area(xs, ys)
        st.session_state.submitted = True

        st.sidebar.success(f"Sheet: {st.session_state.map_number}")

# ---------------- CONVERT VIEW ----------------
if st.sidebar.button("🔄 Toggle WGS84 View"):
    st.session_state.view_mode = "WGS84" if st.session_state.view_mode == "ETM" else "ETM"
    st.sidebar.info(f"View mode: {st.session_state.view_mode}")

# ---------------- AREA ----------------
if st.session_state.area_m2:
    st.sidebar.info(f"Area: {st.session_state.area_m2:.2f} m²")
    # st.sidebar.info(f"Area: {st.session_state.area_m2/10000:.4f} ha")

# ---------------- KML ----------------
kml_data = None

if st.sidebar.button("📁 Generate KML"):

    if len(st.session_state.points_etm) >= 3:

        kml = simplekml.Kml()
        coords = []

        for x, y in st.session_state.points_etm:
            lon, lat = etm_to_wgs.transform(x, y)
            coords.append((lon, lat))

        coords.append(coords[0])

        poly = kml.newpolygon(name="area")
        poly.outerboundaryis = coords

        file_path = "parcel.kml"
        kml.save(file_path)

        with open(file_path, "rb") as f:
            kml_data = f.read()

if kml_data:
    st.sidebar.download_button("⬇ Download KML", kml_data, file_name="area.kml")

# ---------------- TIFF (ONLY AFTER SUBMIT) ----------------
tif_file = None

if st.session_state.submitted:
    tif_file = st.sidebar.file_uploader(
        f"Load TIFF for Sheet {st.session_state.map_number}",
        type=["tif", "tiff"]
    )

# =========================================================
# MAP
# =========================================================
if st.session_state.points_etm:

    pts = np.array(st.session_state.points_etm)

    xs, ys = pts[:, 0], pts[:, 1]

    centroid_x, centroid_y = np.mean(xs), np.mean(ys)

    fig = go.Figure()

    # ---------------- TIFF ----------------
    if tif_file:
        with rasterio.open(tif_file) as src:
            left, bottom, right, top = src.bounds

            img = src.read()
            if img.shape[0] == 1:
                img = np.repeat(img, 3, axis=0)

            img = np.transpose(img[:3], (1, 2, 0))
            img = (img - img.min()) / (img.max() - img.min() + 1e-9)
            img = (img * 255).astype(np.uint8)

            buf = BytesIO()
            Image.fromarray(img).save(buf, format="PNG")

            encoded = base64.b64encode(buf.getvalue()).decode()

            fig.add_layout_image(dict(
                source="data:image/png;base64," + encoded,
                xref="x",
                yref="y",
                x=left,
                y=top,
                sizex=(right - left),
                sizey=(top - bottom),
                sizing="stretch",
                layer="below"
            ))

    # ---------------- POLYGON ----------------
    fig.add_trace(go.Scatter(
        x=xs,
        y=ys,
        mode="lines+markers",
        fill="toself",
        name="area"
    ))

    fig.add_trace(go.Scatter(
        x=[centroid_x],
        y=[centroid_y],
        mode="markers",
        marker=dict(size=12, color="blue"),
        name="Centroid"
    ))

    # FIX DISTORTION
    fig.update_yaxes(scaleanchor="x", scaleratio=1)

    fig.update_layout(
        height=850,
        title=f"Parcel — {st.session_state.map_number}",
        dragmode="pan",
        plot_bgcolor="#048c41"
    )

    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})

else:
    st.info("Add points → Submit → Load TIFF → Export KML")
