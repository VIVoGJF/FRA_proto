import geopandas as gpd
import rasterio
import rasterio.mask
import numpy as np
import pandas as pd
import os
import json
from pathlib import Path

def process_raster(raster_path, geojson_path, output_geojson, output_csv):
    """
    Clip raster by FRA polygons and compute land-use stats.
    Outputs enriched GeoJSON + CSV summary.
    """

    # Load polygons
    gdf = gpd.read_file(geojson_path)

    # Open raster
    raster = rasterio.open(raster_path)

    results = []
    enriched = []

    for idx, row in gdf.iterrows():
        geom = [row["geometry"].__geo_interface__]

        try:
            out_img, out_transform = rasterio.mask.mask(raster, geom, crop=True)
            data = out_img[0]
            data = data[data != raster.nodata]

            if data.size == 0:
                continue

            unique, counts = np.unique(data, return_counts=True)
            total = counts.sum()

            land_stats = {int(k): int(v) for k, v in zip(unique, counts)}
            row_dict = row.to_dict()
            row_dict["land_stats"] = land_stats
            row_dict["total_pixels"] = int(total)
            enriched.append(row_dict)

            results.append({
                "district": row.get("district", ""),
                "block": row.get("block", ""),
                "village": row.get("village", ""),
                "land_stats": json.dumps(land_stats),  # ✅ store as JSON string
                "total_pixels": int(total)
            })

        except Exception as e:
            print(f"⚠️ Failed for village {row.get('village', '')}: {e}")

    # ----------------------------
    # Save enriched GeoJSON
    # ----------------------------
    if enriched:
        result_gdf = gpd.GeoDataFrame(pd.DataFrame(enriched), crs=gdf.crs)

        # Ensure no dict/list leaks into GeoJSON
        for col in result_gdf.columns:
            result_gdf[col] = result_gdf[col].apply(
                lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x
            )

        os.makedirs(os.path.dirname(output_geojson), exist_ok=True)
        result_gdf.to_file(output_geojson, driver="GeoJSON")
        print(f"✅ Saved enriched landuse GeoJSON → {output_geojson}")

    # ----------------------------
    # Save CSV summary
    # ----------------------------
    if results:
        pd.DataFrame(results).to_csv(output_csv, index=False)
        print(f"✅ Saved landuse CSV → {output_csv}")


if __name__ == "__main__":
    base = Path.cwd()
    raster_path = base / "data" / "raw" / "satellite" / "od_cover.tif"
    geojson_path = base / "data" / "processed" / "geojson" / "fra.geojson"
    output_geojson = base / "data" / "processed" / "geojson" / "fra_landuse.geojson"
    output_csv = base / "data" / "processed" / "features" / "landuse.csv"

    os.makedirs(output_geojson.parent, exist_ok=True)
    os.makedirs(output_csv.parent, exist_ok=True)

    process_raster(raster_path, geojson_path, output_geojson, output_csv)
