import geopandas as gpd
import rasterio
import rasterio.mask
import numpy as np
from shapely.geometry import shape, mapping
from rasterio.features import shapes
from pathlib import Path
import os
import json

# Land cover mapping (update if needed)
CLASS_MAP = {
    10: "tree_cover",
    40: "cropland",
    50: "built_up",
    80: "water_bodies"
}

def extract_and_merge_assets(raster_path, fra_geojson, output_geojson):
    """
    Clip each FRA village, classify pixels into 4 classes,
    vectorize them, and output one merged GeoJSON.
    """

    # Load FRA polygons
    gdf = gpd.read_file(fra_geojson)

    # Open raster
    raster = rasterio.open(raster_path)

    features = []
    total = len(gdf)

    for idx, row in gdf.iterrows():
        geom = [row["geometry"].__geo_interface__]

        try:
            # Clip raster by village
            out_img, out_transform = rasterio.mask.mask(raster, geom, crop=True)
            data = out_img[0]
            data[data == raster.nodata] = 0  # remove nodata

            if np.all(data == 0):
                continue

            # Polygonize per land cover class
            mask = data != 0
            for shp, val in shapes(data, mask=mask, transform=out_transform):
                val = int(val)
                if val not in CLASS_MAP:
                    continue

                feat = {
                    "type": "Feature",
                    "geometry": shp,
                    "properties": {
                        "district": row.get("district", ""),
                        "block": row.get("block", ""),
                        "village": row.get("village", ""),
                        "land_type": CLASS_MAP[val],
                        "area_pixels": int((np.array(shp["coordinates"][0]).shape[0]))
                    }
                }
                features.append(feat)

        except Exception as e:
            print(f"⚠️ Error in {row.get('village','')} → {e}")

        # Progress
        percent = round((idx+1)/total * 100, 2)
        print(f"✅ Processed {idx+1}/{total} villages ({percent}%)")

    # Final merged GeoJSON
    fc = {"type": "FeatureCollection", "features": features}

    os.makedirs(os.path.dirname(output_geojson), exist_ok=True)
    with open(output_geojson, "w", encoding="utf-8") as f:
        json.dump(fc, f, separators=(",", ":"))

    print(f"\n🎉 Final village asset map saved → {output_geojson}")
    print(f"Total features: {len(features)}")


if __name__ == "__main__":
    base = Path.cwd()
    raster_path = base / "data" / "raw" / "satellite" / "od_cover.tif"
    fra_geojson = base / "data" / "processed" / "geojson" / "fra.geojson"
    output_geojson = base / "data" / "processed" / "geojson" / "fra_villagemap.geojson"

    extract_and_merge_assets(raster_path, fra_geojson, output_geojson)
