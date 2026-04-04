# import frappe
# from frappe import _ as _t

# # reuse your existing mapper if available
# try:
#     from farmportal.api.requests import _get_party_from_user
# except Exception:
#     def _get_party_from_user(user):
#         return None, None

# @frappe.whitelist()
# def begin_import():
#     """Create a Land Plot Import doc (Draft) linked to logged-in supplier and return its name."""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_t("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_t("Only Suppliers can upload"), frappe.PermissionError)

#     doc = frappe.get_doc({
#         "doctype": "Land Plot Import",
#         "supplier": supplier,
#         "status": "Draft",
#     })
#     doc.insert(ignore_permissions=True)
#     frappe.db.commit()
#     return {"name": doc.name}

# @frappe.whitelist()
# def finalize_import(name: str, total_plots: int = 0, log: str | None = None, status: str | None = None):
#     """Mark an import as Imported (or Failed) and store counts/log."""
#     doc = frappe.get_doc("Land Plot Import", name)
#     doc.total_plots = int(total_plots or 0)
#     if status and status in {"Draft", "Imported", "Failed"}:
#         doc.status = status
#     else:
#         doc.status = "Imported"
#     if log is not None:
#         doc.log = log
#     doc.save(ignore_permissions=True)
#     frappe.db.commit()
#     return {"ok": True, "name": name, "file_url": doc.source_file}
# import frappe
# import json
# from frappe import _

# # Helper function to get supplier from user
# def _get_party_from_user(user):
#     """Get supplier from user - adjust this based on your app structure"""
#     # You may need to adjust this logic based on how suppliers are linked to users in your app
#     supplier_list = frappe.get_all("Supplier", 
#         filters={"custom_user": user}, 
#         fields=["name"]
#     )
#     if supplier_list:
#         return None, supplier_list[0].name
#     return None, None

# @frappe.whitelist()
# def get_land_plots():
#     """Get all land plots for the logged-in supplier"""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can access land plots"), frappe.PermissionError)

#     plots = frappe.get_all("Land Plot", 
#         filters={"supplier": supplier},
#         fields=[
#             "name", "plot_id", "plot_name", "country", "area", 
#             "coordinates", "geojson", "latitude", "longitude",
#             "commodities", "deforestation_percentage", "deforested_area",
#             "deforested_polygons"
#         ]
#     )
    
#     # Parse JSON fields and add products
#     for plot in plots:
#         try:
#             if plot.coordinates:
#                 plot.coordinates = json.loads(plot.coordinates)
#             if plot.geojson:
#                 plot.geojson = json.loads(plot.geojson)
#             if plot.deforested_polygons:
#                 plot.deforested_polygons = json.loads(plot.deforested_polygons)
#         except:
#             pass
            
#         # Get products
#         products = frappe.get_all("Land Plot Product",
#             filters={"parent": plot.name},
#             fields=["product", "product_name"]
#         )
#         plot.products = [p.product for p in products]
        
#         # Parse commodities 
#         if plot.commodities:
#             plot.commodities = [c.strip() for c in plot.commodities.split(',')]
#         else:
#             plot.commodities = []
    
#     return {"data": plots}

# @frappe.whitelist()
# def create_land_plot(plot_data):
#     """Create a new land plot"""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can create land plots"), frappe.PermissionError)

#     data = json.loads(plot_data) if isinstance(plot_data, str) else plot_data
    
#     # Create the main document
#     doc = frappe.get_doc({
#         "doctype": "Land Plot",
#         "plot_id": data.get("id") or data.get("plot_id"),
#         "plot_name": data.get("name") or data.get("plot_name"),
#         "supplier": supplier,
#         "country": data.get("country"),
#         "area": data.get("area", 0),
#         "coordinates": json.dumps(data.get("coordinates", [])) if data.get("coordinates") else None,
#         "geojson": json.dumps(data.get("geojson")) if data.get("geojson") else None,
#         "latitude": data.get("latitude"),
#         "longitude": data.get("longitude"),
#         "commodities": ",".join(data.get("commodities", [])),
#         "deforestation_percentage": data.get("deforestationData", {}).get("percentage", 0),
#         "deforested_area": data.get("deforestationData", {}).get("deforestedArea", 0),
#         "deforested_polygons": json.dumps(data.get("deforestationData", {}).get("deforestedPolygons")) if data.get("deforestationData", {}).get("deforestedPolygons") else None
#     })
    
#     # Add products
#     for product_id in data.get("products", []):
#         doc.append("products", {
#             "product": product_id
#         })
    
#     doc.insert(ignore_permissions=True)
#     frappe.db.commit()
    
#     return {"name": doc.name, "plot_id": doc.plot_id}

# @frappe.whitelist()
# def update_land_plot(name, plot_data):
#     """Update an existing land plot"""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can update land plots"), frappe.PermissionError)

#     data = json.loads(plot_data) if isinstance(plot_data, str) else plot_data
    
#     doc = frappe.get_doc("Land Plot", name)
    
#     # Check ownership
#     if doc.supplier != supplier:
#         frappe.throw(_("Access denied"), frappe.PermissionError)
    
#     # Update fields
#     doc.plot_id = data.get("id") or data.get("plot_id", doc.plot_id)
#     doc.plot_name = data.get("name") or data.get("plot_name", doc.plot_name) 
#     doc.country = data.get("country", doc.country)
#     doc.area = data.get("area", doc.area)
#     doc.coordinates = json.dumps(data.get("coordinates", [])) if data.get("coordinates") else doc.coordinates
#     doc.geojson = json.dumps(data.get("geojson")) if data.get("geojson") else doc.geojson
#     doc.commodities = ",".join(data.get("commodities", [])) if data.get("commodities") else doc.commodities
    
#     # Update products - clear and re-add
#     doc.products = []
#     for product_id in data.get("products", []):
#         doc.append("products", {"product": product_id})
    
#     doc.save(ignore_permissions=True)
#     frappe.db.commit()
    
#     return {"success": True}

# @frappe.whitelist()
# def delete_land_plot(name):
#     """Delete a land plot"""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can delete land plots"), frappe.PermissionError)

#     doc = frappe.get_doc("Land Plot", name)
    
#     if doc.supplier != supplier:
#         frappe.throw(_("Access denied"), frappe.PermissionError)
    
#     frappe.delete_doc("Land Plot", name)
#     frappe.db.commit()
    
#     return {"success": True}

# @frappe.whitelist()
# def bulk_create_land_plots(plots_data):
#     """Create multiple land plots from CSV import"""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can create land plots"), frappe.PermissionError)

#     plots = json.loads(plots_data) if isinstance(plots_data, str) else plots_data
#     created_plots = []
    
#     for plot_data in plots:
#         try:
#             result = create_land_plot(plot_data)
#             created_plots.append(result)
#         except Exception as e:
#             frappe.log_error(f"Failed to create plot {plot_data.get('id', 'unknown')}: {str(e)}")
    
#     return {"created": len(created_plots), "plots": created_plots}

# # Keep the existing import functions for file handling
# @frappe.whitelist()
# def begin_import():
#     """Create a Land Plot Import doc (Draft) linked to logged-in supplier and return its name."""
#     user = frappe.session.user
#     if user == "Guest":
#         frappe.throw(_("Not logged in"), frappe.PermissionError)

#     customer, supplier = _get_party_from_user(user)
#     if not supplier:
#         frappe.throw(_("Only Suppliers can upload"), frappe.PermissionError)

#     doc = frappe.get_doc({
#         "doctype": "Land Plot Import",
#         "supplier": supplier,
#         "status": "Draft",
#     })
#     doc.insert(ignore_permissions=True)
#     frappe.db.commit()
#     return {"name": doc.name}

# @frappe.whitelist()
# def finalize_import(name: str, total_plots: int = 0, log: str | None = None, status: str | None = None):
#     """Mark an import as Imported (or Failed) and store counts/log."""
#     doc = frappe.get_doc("Land Plot Import", name)
#     doc.total_plots = int(total_plots or 0)
#     if status and status in {"Draft", "Imported", "Failed"}:
#         doc.status = status
#     else:
#         doc.status = "Imported"
#     if log is not None:
#         doc.log = log
#     doc.save(ignore_permissions=True)
#     frappe.db.commit()
#     return {"ok": True, "name": name, "file_url": doc.source_file}


#old configuration for fetching earth engine-key frm file

# import frappe
# import json
# import os
# import ee
# import uuid
# from datetime import datetime
# from frappe import _

# # Earth Engine Configuration
# CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# PRIVATE_KEY_PATH = os.path.join(CURRENT_DIR, "earthengine-key.json")
# SERVICE_ACCOUNT = 'map-integration@igneous-nucleus-442113-m1.iam.gserviceaccount.com'

# # Initialize Earth Engine
# def init_earth_engine():
#     """Initialize Earth Engine with service account credentials"""
#     try:
#         if not ee.data._credentials:
#             credentials = ee.ServiceAccountCredentials(SERVICE_ACCOUNT, PRIVATE_KEY_PATH)
#             ee.Initialize(credentials, project='igneous-nucleus-442113-m1')
#     except Exception as e:
#         safe_log_error(f"Earth Engine initialization failed: {str(e)}")
#         print(f"Earth Engine init failed: {e}")

# def safe_log_error(message, title=None, method="API"):
#     """Safely log errors with proper length handling"""
#     try:
#         MAX_LENGTH = 135  # Leave some buffer for 140 char limit
#         if title:
#             truncated_title = (title[:MAX_LENGTH - 3] + '...') if len(title) > MAX_LENGTH else title
#         else:
#             truncated_title = (message[:MAX_LENGTH - 3] + '...') if len(message) > MAX_LENGTH else message
        
#         # Use frappe's built-in logging
#         frappe.log_error(message=message, title=truncated_title)
#     except Exception as e:
#         # If even logging fails, just print to console
#         print(f"Logging failed: {str(e)}")
#         print(f"Original error: {message}")

# Earth Engine Configuration from site config

import frappe
import json
import os
import ee
import uuid
import tempfile
from datetime import datetime
from frappe import _

DEFAULT_SINGLE_POINT_RADIUS_M = 100.0
_EE_READY = False


def get_ee_config():
    """Get Earth Engine configuration from site config"""
    return frappe.conf.get("earth_engine", {})

def init_earth_engine():
    """Initialize Earth Engine with service account credentials from site config"""
    global _EE_READY
    if _EE_READY:
        return

    print("[DEBUG] Initializing Earth Engine...")  # [DEBUG]
    try:
        ee_config = get_ee_config()
        
        if not ee_config:
            error_msg = "Earth Engine configuration not found in site_config.json"
            safe_log_error(error_msg)
            print(f"[DEBUG] {error_msg}")  # [DEBUG]
            return
        
        service_account = ee_config.get("service_account")
        project = ee_config.get("project")
        private_key_json = ee_config.get("private_key")
        
        if not all([service_account, project, private_key_json]):
            error_msg = "Incomplete Earth Engine configuration in site_config.json"
            safe_log_error(error_msg)
            print(f"[DEBUG] {error_msg}")  # [DEBUG]
            return

        # Fast path: EE already initialized in this process.
        if ee.data._credentials:
            _EE_READY = True
            return
        
        # Create temporary file for credentials (EE requires file path)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
            json.dump(private_key_json, temp_file)
            temp_key_path = temp_file.name
        
        try:
            credentials = ee.ServiceAccountCredentials(service_account, temp_key_path)
            try:
                ee.Initialize(credentials, project=project)
                print("[DEBUG] Earth Engine initialized successfully.")  # [DEBUG]
                _EE_READY = True
            except Exception as e:
                if "already been initialized" in str(e):
                    print("[DEBUG] Earth Engine already initialized.")  # [DEBUG]
                    _EE_READY = True
                else:
                    raise
        finally:
            # Clean up temporary file
            if os.path.exists(temp_key_path):
                os.unlink(temp_key_path)
                
    except Exception as e:
        _EE_READY = False
        safe_log_error(f"Earth Engine initialization failed: {str(e)}")
        print(f"[DEBUG] Earth Engine initialization failed: {e}")  # [DEBUG]

def safe_log_error(message, title=None, method="API"):
    print(f"[DEBUG] Logging error: {message} (title={title}, method={method})")  # [DEBUG]
    try:
        MAX_LENGTH = 135
        if title:
            truncated_title = (title[:MAX_LENGTH - 3] + '...') if len(title) > MAX_LENGTH else title
        else:
            truncated_title = (message[:MAX_LENGTH - 3] + '...') if len(message) > MAX_LENGTH else message
        frappe.log_error(message=message, title=truncated_title)
    except Exception as e:
        print(f"[DEBUG] Logging failed: {str(e)}")  # [DEBUG]
        print(f"[DEBUG] Original error: {message}")  # [DEBUG]


def generate_unique_plot_id(base_id=None, supplier=None):
    """Generate a unique plot ID"""
    if base_id:
        # Clean the base ID
        import re
        clean_id = re.sub(r'[^a-zA-Z0-9-_]', '', str(base_id).strip())
        if clean_id and len(clean_id) > 0:
            # Check if it already exists for this supplier
            existing = frappe.db.exists("Land Plot", {"plot_id": clean_id, "supplier": supplier})
            if not existing:
                return clean_id
            
            # If exists, try with suffix
            for i in range(1, 100):
                new_id = f"{clean_id}-{i:02d}"
                existing = frappe.db.exists("Land Plot", {"plot_id": new_id, "supplier": supplier})
                if not existing:
                    return new_id
    
    # Generate a unique timestamp-based ID
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    unique_suffix = str(uuid.uuid4())[:8].upper()
    return f"PLOT-{timestamp}-{unique_suffix}"

def _to_positive_float(value):
    try:
        v = float(value)
        return v if v > 0 else None
    except Exception:
        return None

def _normalize_coordinates_to_polygon(coordinates):
    """Normalize point/polygon coordinates to a closed polygon ring."""
    if not coordinates or len(coordinates) == 0:
        return None

    # Single point fallback for polygon-only callers.
    if len(coordinates) == 1:
        lng, lat = coordinates[0]
        buffer_size = 0.001
        return [
            [lng - buffer_size, lat - buffer_size],
            [lng + buffer_size, lat - buffer_size],
            [lng + buffer_size, lat + buffer_size],
            [lng - buffer_size, lat + buffer_size],
            [lng - buffer_size, lat - buffer_size],
        ]

    coords = coordinates.copy()
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords

def _build_analysis_geometry(coordinates, area_ha=None):
    """Build EE geometry. Single-point plots use area-based circular buffer."""
    if not coordinates or len(coordinates) == 0:
        return None

    if len(coordinates) == 1:
        lng, lat = coordinates[0]
        area_value = _to_positive_float(area_ha)
        if area_value:
            # Area-based circle so risk math aligns with Land Plot area.
            area_m2 = area_value * 10000.0
            radius_m = (area_m2 / 3.141592653589793) ** 0.5
        else:
            radius_m = DEFAULT_SINGLE_POINT_RADIUS_M
        return ee.Geometry.Point([lng, lat]).buffer(radius_m)

    coords = _normalize_coordinates_to_polygon(coordinates)
    if not coords:
        return None
    return ee.Geometry.Polygon([coords])

def _build_deforestation_inputs(geometry):
    """
    Build Hansen + Sentinel-2 masks for combined deforestation analysis.
    Combined loss is computed as UNION(Hansen loss, Sentinel NDVI-loss).
    """
    gfc = ee.Image("UMD/hansen/global_forest_change_2024_v1_12")
    tree_cover_2000 = gfc.select("treecover2000")
    loss_year = gfc.select("lossyear")

    # Baseline forest mask from Hansen.
    forest_mask = tree_cover_2000.gte(30).rename("forest")

    # Hansen loss after 2020 baseline.
    hansen_loss_mask = loss_year.gt(20).And(forest_mask).rename("hansen_loss")

    sentinel_loss_mask = None
    try:
        s2 = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(geometry)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        )

        s2_2020 = s2.filterDate("2019-01-01", "2020-12-31").median()
        s2_recent = s2.filterDate("2024-01-01", "2026-01-01").median()

        ndvi_2020 = s2_2020.normalizedDifference(["B8", "B4"])
        ndvi_recent = s2_recent.normalizedDifference(["B8", "B4"])
        ndvi_change = ndvi_2020.subtract(ndvi_recent)

        sentinel_loss_mask = ndvi_change.gt(0.25).And(forest_mask).rename("sentinel_loss")
    except Exception as sentinel_error:
        # Do not fail overall analysis if Sentinel processing fails.
        safe_log_error(
            f"Sentinel-2 deforestation calculation failed; using Hansen only: {str(sentinel_error)}",
            "Sentinel Calc Warning"
        )

    if sentinel_loss_mask is None:
        sentinel_loss_mask = ee.Image.constant(0).rename("sentinel_loss").clip(geometry)

    combined_loss_mask = hansen_loss_mask.Or(sentinel_loss_mask).rename("combined_loss")

    return {
        "tree_cover_2000": tree_cover_2000,
        "loss_year": loss_year,
        "forest_mask": forest_mask,
        "hansen_loss_mask": hansen_loss_mask,
        "sentinel_loss_mask": sentinel_loss_mask,
        "combined_loss_mask": combined_loss_mask,
    }

def _calculate_deforestation_stats(geometry, forest_mask, combined_loss_mask):
    """Calculate area and percentage metrics from forest/loss masks."""
    pixel_area = ee.Image.pixelArea()
    forest_area_img = forest_mask.rename("forest").multiply(pixel_area)
    loss_area_img = combined_loss_mask.rename("loss").multiply(pixel_area)

    reduce_kwargs = {
        "reducer": ee.Reducer.sum(),
        "geometry": geometry,
        "scale": 10,
        "maxPixels": 1e10,
        "bestEffort": True,
        "tileScale": 4,
    }

    forest_area_dict = forest_area_img.reduceRegion(**reduce_kwargs)
    loss_area_dict = loss_area_img.reduceRegion(**reduce_kwargs)

    forest_area = ee.Number(
        ee.Algorithms.If(forest_area_dict.get("forest"), forest_area_dict.get("forest"), 0)
    )
    loss_area = ee.Number(
        ee.Algorithms.If(loss_area_dict.get("loss"), loss_area_dict.get("loss"), 0)
    )

    forest_area_ha = forest_area.divide(10000)
    loss_area_ha = loss_area.divide(10000)
    loss_percent = ee.Algorithms.If(
        forest_area_ha.gt(0),
        loss_area_ha.divide(forest_area_ha).multiply(100),
        0
    )

    stats = ee.Dictionary({
        "forest_area_ha": forest_area_ha,
        "loss_area_ha": loss_area_ha,
        "deforestation_percent": loss_percent
    }).getInfo()

    return {
        "forest_area_ha": round(stats["forest_area_ha"], 2),
        "loss_area_ha": round(stats["loss_area_ha"], 2),
        "deforestation_percent": round(stats["deforestation_percent"], 2)
    }

def calculate_deforestation_data(coordinates, area_ha=None, ensure_init=True):
    """Calculate deforestation data for given coordinates"""
    try:
        if ensure_init:
            init_earth_engine()
        
        geometry = _build_analysis_geometry(coordinates, area_ha=area_ha)
        if not geometry:
            return None

        masks = _build_deforestation_inputs(geometry)
        return _calculate_deforestation_stats(
            geometry,
            masks["forest_mask"],
            masks["combined_loss_mask"],
        )

    except Exception as e:
        safe_log_error(f"Deforestation calculation failed: {str(e)}", "Deforestation Error")
        return None

        
@frappe.whitelist()
def get_deforestation_tiles(coordinates_json, area_ha=None):
    """Generate Earth Engine tile URLs for deforestation visualization"""
    try:
        init_earth_engine()
        
        coordinates = json.loads(coordinates_json)
        geometry = _build_analysis_geometry(coordinates, area_ha=area_ha)
        if not geometry:
            frappe.throw(_("Invalid coordinates for deforestation analysis"))

        masks = _build_deforestation_inputs(geometry)
        tree_cover_2000 = masks["tree_cover_2000"]
        loss_year = masks["loss_year"]
        forest_mask = masks["forest_mask"]
        hansen_loss_mask = masks["hansen_loss_mask"]

        # Create visualization parameters
        # Tree cover visualization (green shades)
        tree_cover_vis = {
            "min": 30, 
            "max": 100, 
            "palette": ["#d9f0a3", "#addd8e", "#78c679", "#41ab5d", "#238443", "#006837", "#004529"]
        }
        
        # Deforestation visualization (red)
        deforestation_vis = {
            "min": 1, 
            "max": 1, 
            "palette": ["red"]
        }
        
        # Loss year visualization (color by year)
        loss_year_vis = {
            "min": 21, 
            "max": 24, 
            "palette": ["yellow", "orange", "red", "darkred"]
        }

        # Generate tile URLs
        tree_cover_tile_info = tree_cover_2000.updateMask(forest_mask).getMapId(tree_cover_vis)
        # Keep this as Hansen layer for visual continuity; stats below use combined logic.
        deforestation_tile_info = hansen_loss_mask.selfMask().getMapId(deforestation_vis)
        loss_year_tile_info = loss_year.updateMask(loss_year.gt(20)).getMapId(loss_year_vis)

        stats = _calculate_deforestation_stats(
            geometry,
            masks["forest_mask"],
            masks["combined_loss_mask"],
        )

        return {
            "tree_cover_tile_url": tree_cover_tile_info['tile_fetcher'].url_format,
            "deforestation_tile_url": deforestation_tile_info['tile_fetcher'].url_format,
            "loss_year_tile_url": loss_year_tile_info['tile_fetcher'].url_format,
            "forest_area_ha": stats["forest_area_ha"],
            "loss_area_ha": stats["loss_area_ha"],
            "deforestation_percent": stats["deforestation_percent"]
        }

    except Exception as e:
        safe_log_error(f"Error generating tile URLs: {str(e)}", "Tile Generation Error")
        frappe.throw(f"Error generating tile URLs: {str(e)}")

@frappe.whitelist()
def get_global_deforestation_tiles():
    """Generate global Earth Engine tile URLs for background deforestation layers"""
    try:
        init_earth_engine()

        # Load Hansen dataset
        gfc = ee.Image("UMD/hansen/global_forest_change_2024_v1_12")
        tree_cover_2000 = gfc.select("treecover2000")
        loss_year = gfc.select("lossyear")

        # Global layers
        forest_mask = tree_cover_2000.gte(30)
        loss_after_2020 = loss_year.gt(20)

        # Visualization parameters
        tree_cover_vis = {
            "min": 30, 
            "max": 100, 
            "palette": ["#d9f0a3", "#addd8e", "#78c679", "#41ab5d", "#238443", "#006837", "#004529"]
        }
        
        deforestation_vis = {
            "min": 1, 
            "max": 1, 
            "palette": ["#ff0000"]
        }

        canopy_loss_vis = {
            "min": 1,
            "max": 1,
            "palette": ["#ff8c00"]
        }

        # Generate global tile URLs
        global_tree_cover = tree_cover_2000.updateMask(forest_mask).getMapId(tree_cover_vis)
        global_deforestation = loss_after_2020.selfMask().getMapId(deforestation_vis)
        global_canopy_loss_url = None

        # Sentinel-2 canopy loss (baseline vs recent NDVI drop, masked by forest)
        try:
            s2 = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
            )
            s2_2020 = s2.filterDate("2019-01-01", "2020-12-31").median()
            s2_recent = s2.filterDate("2024-01-01", "2026-01-01").median()

            ndvi_2020 = s2_2020.normalizedDifference(["B8", "B4"])
            ndvi_recent = s2_recent.normalizedDifference(["B8", "B4"])
            ndvi_change = ndvi_2020.subtract(ndvi_recent)

            recent_canopy_loss = ndvi_change.gt(0.25).And(forest_mask)
            global_canopy_loss = recent_canopy_loss.selfMask().getMapId(canopy_loss_vis)
            global_canopy_loss_url = global_canopy_loss["tile_fetcher"].url_format
        except Exception as sentinel_error:
            safe_log_error(
                f"Sentinel-2 canopy loss tile generation failed: {str(sentinel_error)}",
                "Sentinel Layer Error"
            )

        return {
            "global_tree_cover_url": global_tree_cover['tile_fetcher'].url_format,
            "global_deforestation_url": global_deforestation['tile_fetcher'].url_format,
            "global_canopy_loss_url": global_canopy_loss_url
        }

    except Exception as e:
        safe_log_error(f"Error generating global tile URLs: {str(e)}", "Global Tile Error")
        frappe.throw(f"Error generating global tile URLs: {str(e)}")


USER_LINK_FIELDS = {
    "Customer": ["custom_user", "user_id", "user"],
    "Supplier": ["custom_user", "user_id", "user"],
}


def _get_user_email(user: str) -> str | None:
    try:
        return frappe.db.get_value("User", user, "email")
    except Exception:
        return None


def _link_by_contact_email(user: str, target_doctype: str) -> str | None:
    """Fallback: User -> Contact(Email) -> Dynamic Link -> target doctype."""
    email = _get_user_email(user)
    if not email:
        return None

    contact_names = []

    # Preferred path for ERPNext contacts.
    try:
        contact_rows = frappe.get_all("Contact Email", filters={"email_id": email}, fields=["parent"])
        contact_names.extend([row.get("parent") for row in contact_rows if row.get("parent")])
    except Exception:
        pass

    # Fallback path for instances storing email directly on Contact.
    if not contact_names:
        try:
            contact_rows = frappe.get_all("Contact", filters={"email_id": email}, fields=["name"])
            contact_names.extend([row.get("name") for row in contact_rows if row.get("name")])
        except Exception:
            pass

    if not contact_names:
        return None

    dl = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "parent": ["in", contact_names],
            "link_doctype": target_doctype,
        },
        fields=["link_name"],
        limit=1,
    )
    return dl[0]["link_name"] if dl else None


def _link_by_user_field(doctype: str, user: str) -> str | None:
    """Try mapping via known User Link fields on the doctype."""
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return None

    for fieldname in USER_LINK_FIELDS.get(doctype, []):
        if meta.has_field(fieldname):
            name = frappe.db.get_value(doctype, {fieldname: user}, "name")
            if name:
                return name
    return None


def _get_party_from_user(user):
    """
    Resolve (customer_name, supplier_name) for this User.
    Supports primary owner users and invited member users linked via Contact.
    """
    customer = _link_by_user_field("Customer", user) or _link_by_contact_email(user, "Customer")
    supplier = _link_by_user_field("Supplier", user) or _link_by_contact_email(user, "Supplier")
    return customer, supplier

@frappe.whitelist()
def get_land_plots():
    """Get all land plots for the logged-in supplier"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can access land plots"), frappe.PermissionError)

    plots = frappe.get_all("Land Plot", 
        filters={"supplier": supplier},
        fields=[
            "name", "plot_id", "farmer_name", "state_province", "country", "area", "yield_dried_mt",
            "coordinates", "geojson", "latitude", "longitude",
            "commodities", "deforestation_percentage", "deforested_area",
            "deforested_polygons"
        ]
    )
    
    # Parse JSON fields and add products
    for plot in plots:
        try:
            if plot.coordinates:
                plot.coordinates = json.loads(plot.coordinates)
            if plot.geojson:
                plot.geojson = json.loads(plot.geojson)
            if plot.deforested_polygons:
                plot.deforested_polygons = json.loads(plot.deforested_polygons)
        except:
            pass
            
        # Get products
        products = frappe.get_all("Land Plot Product",
            filters={"parent": plot.name},
            fields=["product", "product_name"]
        )
        plot.products = [p.product for p in products]
        
        # Parse commodities 
        if plot.commodities:
            plot.commodities = [c.strip() for c in plot.commodities.split(',')]
        else:
            plot.commodities = []
    
    return {"data": plots}

def create_single_plot_internal(plot_data, supplier, calculate_deforestation=True):
    """Internal function to create a single plot with proper unique ID generation"""
    
    # Generate unique plot ID
    unique_plot_id = generate_unique_plot_id(plot_data.get('id'), supplier)
    
    # Double-check for duplicates (safety measure)
    counter = 1
    original_id = unique_plot_id
    while frappe.db.exists("Land Plot", {"plot_id": unique_plot_id, "supplier": supplier}):
        unique_plot_id = f"{original_id}-{counter:03d}"
        counter += 1
        if counter > 999:  # Safety limit
            unique_plot_id = f"PLOT-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            break
    
    raw_area = plot_data.get("area", 0)
    try:
        area_value = float(raw_area or 0)
    except Exception:
        area_value = 0.0

    # Calculate deforestation data only when explicitly requested
    deforestation_data = None
    if calculate_deforestation and plot_data.get('coordinates'):
        coordinates = plot_data.get('coordinates')
        if isinstance(coordinates, str):
            try:
                coordinates = json.loads(coordinates)
            except:
                coordinates = None
        
        if coordinates:
            print(f"Calculating deforestation for plot {unique_plot_id}...")
            try:
                deforestation_data = calculate_deforestation_data(
                    coordinates,
                    area_ha=area_value if area_value > 0 else None,
                )
                if deforestation_data:
                    print(f"Deforestation calculation complete: {deforestation_data['deforestation_percent']}%")
            except Exception as e:
                print(f"Deforestation calculation failed: {str(e)}")
                safe_log_error(f"Deforestation calc failed for {unique_plot_id}: {str(e)}", "Deforestation Error")
                deforestation_data = None
    
    # Create the main document
    meta = frappe.get_meta("Land Plot")
    plot_label = (
        plot_data.get("farmer_name")
        or plot_data.get("name")
        or plot_data.get("plot_name")
        or "Unnamed Plot"
    )

    doc_fields = {
        "doctype": "Land Plot",
        "plot_id": unique_plot_id,  # Use the generated unique ID
        "farmer_name": plot_label,
        "state_province": plot_data.get("state_province", ""),
        "supplier": supplier,
        "country": plot_data.get("country", ""),
        "area": area_value,
        "yield_dried_mt": float(plot_data.get("yield_dried_mt")) if plot_data.get("yield_dried_mt") not in (None, "") else None,
        "latitude": float(plot_data.get("latitude")) if plot_data.get("latitude") else None,
        "longitude": float(plot_data.get("longitude")) if plot_data.get("longitude") else None,
        "coordinates": json.dumps(plot_data.get("coordinates", [])) if plot_data.get("coordinates") else None,
        "geojson": json.dumps(plot_data.get("geojson")) if plot_data.get("geojson") else None,
        "commodities": ",".join(plot_data.get("commodities", [])),
        # Set deforestation data from calculation
        "deforestation_percentage": deforestation_data["deforestation_percent"] if deforestation_data else 0,
        "deforested_area": deforestation_data["loss_area_ha"] if deforestation_data else 0,
        "deforested_polygons": None  # Can be enhanced later
    }
    if meta.has_field("plot_name"):
        doc_fields["plot_name"] = plot_label

    doc = frappe.get_doc(doc_fields)
    
    # Add products
    for product_id in plot_data.get("products", []):
        if product_id:
            doc.append("products", {
                "product": product_id
            })
    
    doc.insert(ignore_permissions=True)
    return {"name": doc.name, "plot_id": doc.plot_id, "deforestation_data": deforestation_data}

@frappe.whitelist()
def create_land_plot(plot_data, calculate_deforestation=True):
    """Create a new land plot with deforestation calculation"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can create land plots"), frappe.PermissionError)

    data = json.loads(plot_data) if isinstance(plot_data, str) else plot_data
    result = create_single_plot_internal(data, supplier, calculate_deforestation)
    frappe.db.commit()
    return result

@frappe.whitelist()
def update_land_plot(name, plot_data, recalculate_deforestation=False):
    """Update an existing land plot with optional deforestation recalculation"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can update land plots"), frappe.PermissionError)

    data = json.loads(plot_data) if isinstance(plot_data, str) else plot_data
    
    doc = frappe.get_doc("Land Plot", name)
    
    # Check ownership
    if doc.supplier != supplier:
        frappe.throw(_("Access denied"), frappe.PermissionError)
    
    # Update fields
    doc.plot_id = data.get("id") or data.get("plot_id", doc.plot_id)
    plot_label = data.get("farmer_name") or data.get("name") or data.get("plot_name") or doc.farmer_name
    doc.farmer_name = plot_label
    if doc.meta.has_field("plot_name"):
        doc.plot_name = plot_label
    doc.state_province = data.get("state_province", doc.state_province)
    doc.country = data.get("country", doc.country)
    doc.area = data.get("area", doc.area)
    if data.get("yield_dried_mt") not in (None, ""):
        doc.yield_dried_mt = data.get("yield_dried_mt")
    doc.coordinates = json.dumps(data.get("coordinates", [])) if data.get("coordinates") else doc.coordinates
    doc.geojson = json.dumps(data.get("geojson")) if data.get("geojson") else doc.geojson
    doc.commodities = ",".join(data.get("commodities", [])) if data.get("commodities") else doc.commodities
    
    # Recalculate deforestation if requested and coordinates changed
    if recalculate_deforestation and data.get('coordinates'):
        coordinates = data.get('coordinates')
        if isinstance(coordinates, str):
            try:
                coordinates = json.loads(coordinates)
            except:
                coordinates = None
        
        if coordinates:
            print(f"Recalculating deforestation for plot {doc.plot_id}...")
            deforestation_data = calculate_deforestation_data(
                coordinates,
                area_ha=data.get("area", doc.area),
            )
            if deforestation_data:
                doc.deforestation_percentage = deforestation_data["deforestation_percent"]
                doc.deforested_area = deforestation_data["loss_area_ha"]
                print(f"Deforestation recalculation complete: {deforestation_data['deforestation_percent']}%")
    
    # Update products - clear and re-add
    doc.products = []
    for product_id in data.get("products", []):
        doc.append("products", {"product": product_id})
    
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    return {"success": True}

@frappe.whitelist()
def bulk_create_land_plots(plots_data, calculate_deforestation=True):
    """Create multiple land plots with proper error handling and unique IDs"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can create land plots"), frappe.PermissionError)

    plots = json.loads(plots_data) if isinstance(plots_data, str) else plots_data
    created_plots = []
    failed_plots = []
    
    # Initialize Earth Engine only when requested
    if calculate_deforestation:
        init_earth_engine()
    
    for i, plot_data in enumerate(plots):
        try:
            # Create plot with unique ID generation
            result = create_single_plot_internal(plot_data, supplier, calculate_deforestation)
            created_plots.append(result)
            frappe.db.commit()  # Commit each successful creation
            
        except Exception as e:
            error_msg = f"Plot {plot_data.get('id', f'Plot_{i+1}')}: {str(e)}"
            failed_plots.append({
                'plot_id': plot_data.get('id', f'Plot_{i+1}'),
                'error': str(e)
            })
            
            # Use safe logging to avoid character length issues
            safe_log_error(error_msg, f"Plot Creation Failed", "bulk_create")
            frappe.db.rollback()  # Rollback this individual failure
            
            print(f"Failed to create plot {plot_data.get('id', f'Plot_{i+1}')}: {str(e)}")
    
    # Final commit for all successful creations
    frappe.db.commit()
    
    return {
        "created": len(created_plots), 
        "failed": len(failed_plots),
        "created_plots": created_plots,
        "failed_plots": failed_plots
    }

@frappe.whitelist()
def recalculate_deforestation(plot_name):
    """Manually recalculate deforestation for a specific plot"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can update land plots"), frappe.PermissionError)

    doc = frappe.get_doc("Land Plot", plot_name)
    
    # Check ownership
    if doc.supplier != supplier:
        frappe.throw(_("Access denied"), frappe.PermissionError)
    
    if not doc.coordinates:
        frappe.throw(_("No coordinates available for deforestation calculation"))
    
    try:
        coordinates = json.loads(doc.coordinates)
        deforestation_data = calculate_deforestation_data(coordinates, area_ha=doc.area)
        
        if deforestation_data:
            doc.deforestation_percentage = deforestation_data["deforestation_percent"]
            doc.deforested_area = deforestation_data["loss_area_ha"]
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            
            return {
                "success": True,
                "deforestation_data": deforestation_data
            }
        else:
            frappe.throw(_("Failed to calculate deforestation data"))
            
    except Exception as e:
        safe_log_error(f"Failed to recalculate deforestation for {plot_name}: {str(e)}", "Deforestation Recalc Error")
        frappe.throw(_("Error calculating deforestation: {0}").format(str(e)))

@frappe.whitelist()
@frappe.whitelist()
def delete_land_plot(name):
    """Delete a land plot"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can delete land plots"), frappe.PermissionError)

    # ✅ Add ignore_permissions=True to bypass doctype-level permission check
    doc = frappe.get_doc("Land Plot", name)
    
    # ✅ Manual validation - check if this user owns the land plot
    if doc.supplier != supplier:
        frappe.throw(_("Access denied: You can only delete your own land plots"), frappe.PermissionError)
    
    # ✅ Use ignore_permissions=True when deleting
    frappe.delete_doc("Land Plot", name, ignore_permissions=True)
    frappe.db.commit()
    
    return {"success": True, "message": _("Land plot deleted successfully")}

    
@frappe.whitelist()
def delete_land_plot(name):
    """Delete a land plot"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can delete land plots"), frappe.PermissionError)

    # ✅ Add ignore_permissions=True to bypass doctype-level permission check
    doc = frappe.get_doc("Land Plot", name)
    
    # ✅ Manual validation - check if this user owns the land plot
    if doc.supplier != supplier:
        frappe.throw(_("Access denied: You can only delete your own land plots"), frappe.PermissionError)
    
    # ✅ Use ignore_permissions=True when deleting
    frappe.delete_doc("Land Plot", name, ignore_permissions=True)
    frappe.db.commit()
    
    return {"success": True, "message": _("Land plot deleted successfully")}


# Keep your existing functions for file import
@frappe.whitelist()
def begin_import():
    """Create a Land Plot Import doc"""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can upload"), frappe.PermissionError)

    doc = frappe.get_doc({
        "doctype": "Land Plot Import",
        "supplier": supplier,
        "status": "Draft",
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name}

@frappe.whitelist()
def finalize_import(name: str, total_plots: int = 0, log: str = None, status: str = None):
    """Mark an import as completed"""
    doc = frappe.get_doc("Land Plot Import", name)
    doc.total_plots = int(total_plots or 0)
    if status and status in {"Draft", "Imported", "Failed"}:
        doc.status = status
    else:
        doc.status = "Imported"
    if log is not None:
        doc.log = log
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "name": name, "file_url": doc.source_file}


@frappe.whitelist()
def get_hubtrace_surveys():
    """Fetch surveys with valid latitude/longitude for Hubtrace import."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can import surveys"), frappe.PermissionError)

    existing_plot_ids = set(
        frappe.get_all("Land Plot", filters={"supplier": supplier}, pluck="plot_id") or []
    )

    rows = frappe.db.sql(
        """
        SELECT s.name AS survey_name, s.plot_number, s.survey_number, s.farmer_name, s.farm_id, b.latitude, b.longitude, b.idx
        FROM `tabSurvey` s
        JOIN `tabBoundary` b
          ON b.parent = s.name
          AND b.parenttype = 'Survey'
          AND b.parentfield = 'farm_boundary'
        WHERE b.latitude IS NOT NULL AND b.longitude IS NOT NULL
        ORDER BY s.name, b.idx
        """,
        as_dict=True
    )

    seen = set()
    results = []
    for row in rows:
        survey_name = row.get("survey_name")
        if not survey_name or survey_name in seen:
            continue
        seen.add(survey_name)

        plot_id = row.get("plot_number") or row.get("farm_id") or survey_name
        latitude = row.get("latitude")
        longitude = row.get("longitude")
        if latitude is None or longitude is None:
            continue

        results.append({
            "survey_name": survey_name,
            "plot_id": plot_id,
            "survey_number": row.get("survey_number"),
            "farm_id": row.get("farm_id"),
            "farmer_name": row.get("farmer_name"),
            "latitude": float(latitude),
            "longitude": float(longitude),
            "imported": plot_id in existing_plot_ids
        })

    return {"data": results}


@frappe.whitelist(methods=["POST"])
def import_hubtrace_survey(survey_name: str):
    """Create a Land Plot from a Survey (first boundary point)."""
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not logged in"), frappe.PermissionError)

    customer, supplier = _get_party_from_user(user)
    if not supplier:
        frappe.throw(_("Only Suppliers can import surveys"), frappe.PermissionError)

    if not survey_name:
        frappe.throw(_("survey_name is required"))

    if not frappe.db.exists("Survey", survey_name):
        frappe.throw(_("Survey not found"))

    survey = frappe.get_doc("Survey", survey_name)

    plot_id = survey.get("plot_number") or survey.get("farm_id") or survey.name
    farmer_name = survey.get("farmer_name") or survey.get("farm_person_name") or ""

    boundary = survey.get("farm_boundary") or []
    coords = []
    for row in boundary:
        if row.latitude is None or row.longitude is None:
            continue
        coords.append([float(row.longitude), float(row.latitude)])

    if not coords:
        frappe.throw(_("Survey has no valid latitude/longitude"))

    # Close polygon if needed
    if len(coords) > 2 and coords[0] != coords[-1]:
        coords.append(coords[0])

    if frappe.db.exists("Land Plot", {"plot_id": plot_id, "supplier": supplier}):
        return {"ok": True, "already_exists": True, "plot_id": plot_id}

    latitude = coords[0][1]
    longitude = coords[0][0]

    plot_data = {
        "id": plot_id,
        "farmer_name": farmer_name,
        "name": farmer_name or plot_id,
        "area": 0,
        "latitude": latitude,
        "longitude": longitude,
        "coordinates": coords,
        "commodities": []
    }

    result = create_single_plot_internal(plot_data, supplier, True)
    frappe.db.commit()

    return {"ok": True, "plot_id": result.get("plot_id"), "name": result.get("name")}
