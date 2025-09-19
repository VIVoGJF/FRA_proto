import geopandas as gpd
import pandas as pd
import os
from pathlib import Path
from rapidfuzz import process


def make_fra_geojson(shapefile_path, csv_path, output_path, state_name="Odisha", threshold=85):
    """
    Filter shapefile polygons to only FRA villages (CSV is reference).
    - Aggregates beneficiaries per (district, block, village)
    - Matches shapefile using hierarchical fuzzy search
    - Geometry comes from shapefile, names come from FRA CSV
    """

    # ----------------------------
    # Load shapefile + FRA CSV
    # ----------------------------
    gdf = gpd.read_file(shapefile_path)
    df = pd.read_csv(csv_path)

    # ----------------------------
    # Normalize shapefile column names
    # ----------------------------
    colmap = {}
    if "district" not in gdf.columns:
        if "district_n" in gdf.columns:
            colmap["district_n"] = "district"
    if "block" not in gdf.columns:
        if "block_name" in gdf.columns:
            colmap["block_name"] = "block"
    if "village" not in gdf.columns:
        if "census_vil" in gdf.columns:
            colmap["census_vil"] = "village"

    gdf = gdf.rename(columns=colmap)
    gdf = gdf[["district", "block", "village", "geometry"]].copy()
    gdf["state"] = state_name

    # Normalize text
    for col in ["district", "block", "village"]:
        gdf[col] = gdf[col].astype(str).str.strip().str.lower()
        df[col] = df[col].astype(str).str.strip().str.lower()

    # ----------------------------
    # Hardcoded corrections
    # ----------------------------
    district_corrections = {
        "anugul": "angul",
        "balasore": "baleswar",
        "baleshwar": "baleswar",
    }
    df["district"] = df["district"].replace(district_corrections)
    gdf["district"] = gdf["district"].replace(district_corrections)

    # ----------------------------
    # Aggregate FRA beneficiaries
    # ----------------------------
    if "num_beneficiaries" not in df.columns:
        df["num_beneficiaries"] = 1

    df_agg = (
        df.groupby(["district", "block", "village"])["num_beneficiaries"]
          .sum()
          .reset_index()
    )

    # ----------------------------
    # Matching
    # ----------------------------
    matched_polygons = []
    unmatched = []

    for _, row in df_agg.iterrows():
        fra_district = row["district"]
        fra_block = row["block"]
        fra_village = row["village"]
        num_beneficiaries = row["num_beneficiaries"]

        candidate = None

        # Step 1: Exact match (district+block+village)
        subset = gdf[
            (gdf["district"] == fra_district) &
            (gdf["block"] == fra_block) &
            (gdf["village"] == fra_village)
        ]
        if not subset.empty:
            candidate = subset.iloc[[0]].copy()

        # Step 2: Fuzzy village match (same block + district)
        if candidate is None:
            subset = gdf[
                (gdf["district"] == fra_district) &
                (gdf["block"] == fra_block)
            ]
            if not subset.empty:
                best = process.extractOne(fra_village, subset["village"], score_cutoff=threshold)
                if best:
                    candidate = subset[subset["village"] == best[0]].iloc[[0]].copy()

        # Step 3: Fuzzy village match (same district)
        if candidate is None:
            subset = gdf[gdf["district"] == fra_district]
            if not subset.empty:
                best = process.extractOne(fra_village, subset["village"], score_cutoff=threshold)
                if best:
                    candidate = subset[subset["village"] == best[0]].iloc[[0]].copy()

        # Step 4: Fuzzy match across whole state
        if candidate is None:
            best = process.extractOne(fra_village, gdf["village"], score_cutoff=threshold)
            if best:
                candidate = gdf[gdf["village"] == best[0]].iloc[[0]].copy()

        # Save if found
        if candidate is not None:
            candidate = candidate.copy()
            # overwrite names with FRA.csv values
            candidate["district"] = fra_district
            candidate["block"] = fra_block
            candidate["village"] = fra_village
            candidate["num_beneficiaries"] = int(num_beneficiaries)
            matched_polygons.append(candidate)
        else:
            unmatched.append((fra_district, fra_block, fra_village))

    # ----------------------------
    # Combine results
    # ----------------------------
    if matched_polygons:
        result_gdf = gpd.GeoDataFrame(pd.concat(matched_polygons, ignore_index=True), crs=gdf.crs)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        result_gdf.to_file(output_path, driver="GeoJSON")
        print(f"✅ Saved FRA GeoJSON with {len(result_gdf)} matched villages at {output_path}")
    else:
        print("⚠️ No matches found at all.")
        return None

    if unmatched:
        print(f"⚠️ {len(unmatched)} villages unmatched. Example: {unmatched[:5]}")

    return output_path


# ----------------------------
# Run script directly
# ----------------------------
if __name__ == "__main__":
    base = Path.cwd()
    shapefile = base / "data" / "raw" / "shapefiles" / "Odisha_Admin_Census_Village_BND_2021.shp"
    fra_csv = base / "data" / "processed" / "text" / "fra.csv"
    output = base / "data" / "processed" / "geojson" / "fra.geojson"

    make_fra_geojson(shapefile, fra_csv, output, state_name="Odisha", threshold=75)
