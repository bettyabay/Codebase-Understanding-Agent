# FDE Onboarding Brief
> Generated: 2026-03-14 22:46 UTC

## The Five Day-One Questions

### 1. What is the primary data ingestion path?

The primary data ingestion path is through the ecom source tables, specifically ecom.raw_customers, ecom.raw_orders, ecom.raw_items, ecom.raw_stores, ecom.raw_products, and ecom.raw_supplies. These are read by the staging models in models/staging/ directory, which transform and clean the raw data before it flows to the marts layer.

### 2. What are the 3–5 most critical output datasets or endpoints?

The 3-5 most critical output datasets are: 1) models/marts/orders - contains calculated order metrics and customer order sequencing, 2) models/marts/order_items - comprehensive sales transaction data with product and supply cost information, 3) models/marts/customers - cleaned customer dataset, 4) models/marts/locations - store location data with operational details, and 5) models/marts/products - product information for analysis.

### 3. What is the blast radius if the most critical module fails?

If the most critical module (models/marts/orders) fails, the blast radius includes all downstream analytics and reporting that depend on order metrics, customer order sequencing, and calculated financial fields. This would impact business intelligence dashboards, customer behavior analysis, and any reporting that relies on order-level aggregations or customer purchase patterns.

### 4. Where is the business logic concentrated vs. distributed?

Business logic is concentrated in the marts layer (models/marts/) where calculations like total cost, subtotal, item counts, and order sequencing occur. The staging layer (models/staging/) contains distributed data cleaning and transformation logic focused on standardizing formats, renaming columns, and converting units (like cents to dollars).

### 5. What has changed most frequently in the last 90 days (high-velocity files)?

Based on the high-velocity files section, there have been 0 commits in the last 30 days for all listed files, indicating no recent changes to the codebase. The most stable files appear to be the macros and marts models, which have had no commits in the last 30 days.

---

## Quick Reference

### Critical Modules
- `models/staging/stg_products` (PageRank: 0.0812)
- `models/staging/stg_supplies` (PageRank: 0.0812)
- `models/staging/stg_orders` (PageRank: 0.0722)
- `models/staging/stg_locations` (PageRank: 0.0686)
- `models/marts/order_items` (PageRank: 0.0595)

### Entry Points (data sources)
- `ecom__raw_customers` — `repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_orders` — `repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_items` — `repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_stores` — `repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_products` — `repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_supplies` — `repo_cache\jaffle_shop\models\staging\__sources.yml`
- `raw_customers` — `repo_cache\jaffle_shop\seeds\jaffle-data\raw_customers.csv`
- `raw_items` — `repo_cache\jaffle_shop\seeds\jaffle-data\raw_items.csv`
- `raw_orders` — `repo_cache\jaffle_shop\seeds\jaffle-data\raw_orders.csv`
- `raw_products` — `repo_cache\jaffle_shop\seeds\jaffle-data\raw_products.csv`

### Final Outputs (data sinks)
- `raw_customers`
- `raw_items`
- `raw_orders`
- `raw_products`
- `raw_stores`
- `raw_supplies`
- `customers`
- `locations`
- `metricflow_time_spine`
- `products`
