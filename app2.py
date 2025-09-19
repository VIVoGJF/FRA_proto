import streamlit as st
import geopandas as gpd
import folium
from pathlib import Path
from streamlit_folium import st_folium
import matplotlib.pyplot as plt
import plotly.express as px


# ----------------------------
# Paths
# ----------------------------
BASE = Path.cwd()
BASE_GEO = BASE / "data" / "processed" / "geojson"
FRA_LANDUSE_PATH = BASE_GEO / "fra_landuse.geojson"
FRA_VILLAGEMAP_PATH = BASE_GEO / "fra_villagemap.geojson"

# ----------------------------
# Cached loaders (speed up reruns)
# ----------------------------
@st.cache_data(show_spinner=False)
def load_landuse():
    g = gpd.read_file(FRA_LANDUSE_PATH)
    if "state" not in g.columns:
        g["state"] = "Odisha"
    return g

@st.cache_data(show_spinner=False)
def load_villagemap():
    g = gpd.read_file(FRA_VILLAGEMAP_PATH)
    if "state" not in g.columns:
        g["state"] = "Odisha"
    return g

fra_landuse = load_landuse()
fra_villagemap = load_villagemap()

# ----------------------------
# Sidebar (cascading filters)
# ----------------------------
st.sidebar.title("Village Selection")

# safe-state list (will exist because loader ensures 'state')
states = sorted(fra_landuse["state"].unique())
state = st.sidebar.selectbox("Select State", states)

districts = sorted(fra_landuse[fra_landuse["state"] == state]["district"].unique())
district = st.sidebar.selectbox("Select District", districts)

blocks = sorted(fra_landuse[
    (fra_landuse["state"] == state) & (fra_landuse["district"] == district)
]["block"].unique())
block = st.sidebar.selectbox("Select Block", blocks)

villages = sorted(fra_landuse[
    (fra_landuse["state"] == state) &
    (fra_landuse["district"] == district) &
    (fra_landuse["block"] == block)
]["village"].unique())
village = st.sidebar.selectbox("Select Village", villages)

# persistent selection so map doesn't disappear after reruns
if "selected_village" not in st.session_state:
    st.session_state.selected_village = None

if st.sidebar.button("View Village"):
    st.session_state.selected_village = (state, district, block, village)

# optional: small Clear button
if st.sidebar.button("Clear Map"):
    st.session_state.selected_village = None

# ----------------------------
# Main app (title + map)
# ----------------------------
st.title("FRA Atlas DSS Prototype")

if not st.session_state.selected_village:
    st.info("Select a village in the sidebar and click **View Village**.")
else:
    state, district, block, village = st.session_state.selected_village

    # village boundary (from fra_landuse)
    village_boundary = fra_landuse[
        (fra_landuse["state"] == state) &
        (fra_landuse["district"] == district) &
        (fra_landuse["block"] == block) &
        (fra_landuse["village"] == village)
    ]

    # village classification polygons (from fra_villagemap)
    village_classes = fra_villagemap[
        (fra_villagemap["state"] == state) &
        (fra_villagemap["district"] == district) &
        (fra_villagemap["block"] == block) &
        (fra_villagemap["village"] == village)
    ]

    # Basic map start: will be re-centered to village
    # If we can compute centroid, start there; otherwise default center
    ESRI_SAT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

    if not village_boundary.empty:
        centroid = village_boundary.geometry.centroid.iloc[0]
        m = folium.Map(
            location=[centroid.y, centroid.x],
            zoom_start=13,
            tiles=ESRI_SAT,
            attr="Esri World Imagery",
            min_zoom=9,
            max_zoom=18
        )
    else:
        m = folium.Map(
            location=[20.3, 85.8],
            zoom_start=7,
            tiles=ESRI_SAT,
            attr="Esri World Imagery",
            min_zoom=4,
            max_zoom=18
        )


    # Color mapping (normalized keys will be used)
    color_map = {
        "treecover": "#228B22",   # green
        "cropland": "#FFD700",    # yellow/orange
        "builtup":  "#FF3333",    # red
        "waterbodies": "#1E90FF"  # blue
    }

    # Determine the classification column name (common possibilities)
    class_col = None
    for candidate in ["land_type", "class", "class_name", "type"]:
        if candidate in village_classes.columns:
            class_col = candidate
            break

    if class_col is None and not village_classes.empty:
        # fallback: try to find a column that contains 'land' or 'class' in its name
        for c in village_classes.columns:
            if "land" in c.lower() or "class" in c.lower():
                class_col = c
                break

    # prepare classification gdf copy and normalized label column
    if not village_classes.empty and class_col:
        vc = village_classes.copy()
        # normalize label (lower, remove spaces/underscores)
        vc["_label_norm"] = vc[class_col].astype(str).str.lower().str.replace(r"[\s_]+", "", regex=True)
    else:
        vc = None

    # If classification polygons exist -> add per-class FeatureGroup (so user can toggle)
    if vc is not None and not vc.empty:
        for key, color in color_map.items():
            subset = vc[vc["_label_norm"] == key]
            if not subset.empty:
                feature_group = folium.FeatureGroup(name=key.capitalize(), show=True)
                folium.GeoJson(
                    subset,
                    style_function=lambda feature, col=color: {
                        "fillColor": col,
                        "color": col,
                        "weight": 2,
                        "fillOpacity": 0.35,   # visible overlay + border
                    },
                    tooltip=folium.GeoJsonTooltip(fields=[class_col], aliases=["Land Type"])
                ).add_to(feature_group)
                feature_group.add_to(m)

    # If no classification columns or polygons, show a subtle message on the map
    if (vc is None) or vc.empty:
        folium.map.Marker(
            (m.location[0], m.location[1]),
            icon=folium.DivIcon(html=f"""<div style="font-size:12px;color:#333;background:rgba(255,255,255,0.8);
                                            padding:4px;border-radius:4px;border:1px solid #999;">
                                         No classification polygons available for this village
                                         </div>""")
        ).add_to(m)

    # Village boundary outline on top
    if not village_boundary.empty:
        gj = folium.GeoJson(
            village_boundary,
            name="Village Boundary",
            style_function=lambda f: {"fillOpacity": 0, "color": "black", "weight": 2}
        ).add_to(m)
        # zoom to village bounds
        try:
            m.fit_bounds(gj.get_bounds())
        except Exception:
            pass


    folium.LayerControl(collapsed=False, position="topright").add_to(m)

    # --- Hide ESRI basemap entry from layer control ---
    # Find and remove the default tile layer's name so it won't show up
    for key, child in list(m._children.items()):
        if isinstance(child, folium.raster_layers.TileLayer):
            if "arcgisonline" in str(child.tiles).lower():
                child.control = False   # disables it from LayerControl



    # Legend (clean, white box with labels)
    legend_html = """
    <div style="
        position: fixed;
        bottom: 30px;
        left: 30px;
        background: white;
        padding: 10px 12px;
        border-radius: 6px;
        border: 1px solid #444;
        box-shadow: 2px 2px 6px rgba(0,0,0,0.25);
        z-index:9999;
        font-size:13px;
        color:#111;">
      <b style="font-size:14px;">Legend</b><br>
      <div style="margin-top:6px;">
        <span style="display:inline-block;width:14px;height:14px;background:%(tree)s;margin-right:8px;border:1px solid #333;vertical-align:middle;"></span> Tree cover<br>
        <span style="display:inline-block;width:14px;height:14px;background:%(crop)s;margin-right:8px;border:1px solid #333;vertical-align:middle;"></span> Cropland<br>
        <span style="display:inline-block;width:14px;height:14px;background:%(built)s;margin-right:8px;border:1px solid #333;vertical-align:middle;"></span> Built-up<br>
        <span style="display:inline-block;width:14px;height:14px;background:%(water)s;margin-right:8px;border:1px solid #333;vertical-align:middle;"></span> Water bodies<br>
      </div>
    </div>
    """ % {"tree": color_map["treecover"], "crop": color_map["cropland"],
           "built": color_map["builtup"], "water": color_map["waterbodies"]}

    m.get_root().html.add_child(folium.Element(legend_html))

    # Render map
    st_folium(m, width=900, height=640)



# ----------------------------
# Village statistics & schemes
# ----------------------------
if st.session_state.selected_village:
    st.subheader("📊 Village Statistics & Recommendations")

    # Create two columns
    col1, col2 = st.columns([1, 1])
    cover_stats = vc.groupby("_label_norm")["area_pixels"].sum()
    cover_stats = cover_stats.reindex(["treecover", "cropland", "builtup", "waterbodies"]).dropna()

    # --- Left side: Beneficiaries + Pie chart ---
    with col1:
        # Number of Beneficiaries
        if not village_boundary.empty and "num_beneficiaries" in village_boundary.columns:
            num_benef = int(village_boundary["num_beneficiaries"].sum())
            st.markdown("##### 👥 Number of Beneficiaries")
            st.write(f"##### **{num_benef:,}**")
        else:
            num_benef = 0
            st.info("No beneficiary data available for this village.")
        
        
        st.markdown("##### 🏷️ Recommended Schemes")

        rec_schemes = []
        if vc is not None and not vc.empty and not cover_stats.empty:
            total_area = cover_stats.sum()
            pct = {k: v / total_area * 100 for k, v in cover_stats.items()} if total_area > 0 else {}

            # Smarter thresholds
            if num_benef > 30:
                rec_schemes.append("MGNREGA")
            if pct.get("cropland", 0) >= 20:
                rec_schemes.append("PM-Kisan Yojana")
            if pct.get("waterbodies", 0) < 5:
                rec_schemes.append("Jal Jeevan Mission")
            if pct.get("treecover", 0) >= 30:
                rec_schemes.append("Van Dhan Yojana")
            if num_benef > 50 and pct.get("builtup", 0) < 10:
                rec_schemes.append("PM Awas Yojana (Gramin)")

        rec_schemes = list(dict.fromkeys(rec_schemes))  # remove duplicates

        if rec_schemes:
            for scheme in rec_schemes:
                st.write(f"- {scheme}")
        else:
            st.info("No specific schemes recommended for this village.")




    # ----------------------------
    # Right column (schemes)
    # ----------------------------
    with col2:
        # Land cover donut chart
        if vc is not None and not vc.empty and "area_pixels" in vc.columns:

            if not cover_stats.empty and cover_stats.sum() > 0:
                import plotly.express as px
                
                #st.markdown("#### Land Cover")
                
                df_plot = cover_stats.reset_index()
                df_plot.columns = ["Land Cover", "Area"]

                pestle_colors = {
                    "treecover": "#2ca02c",   # green
                    "cropland": "#ff7f0e",    # orange
                    "builtup": "#d62728",     # red
                    "waterbodies": "#1f77b4"  # blue
                }

                fig = px.pie(
                    df_plot,
                    values="Area",
                    names="Land Cover",
                    hole=0.45,
                    color="Land Cover",
                    color_discrete_map=pestle_colors,
                )

                fig.update_traces(
                    textposition="outside",
                    textinfo="label+percent",
                    pull=[0.02] * len(df_plot),
                )

                fig.update_layout(
                    showlegend=False,
                    margin=dict(t=100, b=60, l=60, r=60),
                    title ={"text": "Land Cover Distribution", 
                            "x": 0.5, 
                            "xanchor": "center", 
                            "font": {"size": 16, "family": "Arial", "color": "white"}},
                )

                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No valid land cover stats available for this village.")
        else:
            st.info("No land cover data available for this village.")