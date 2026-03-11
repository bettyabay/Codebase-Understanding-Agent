# FDE Onboarding Brief
> Generated: 2026-03-11 22:49 UTC

## The Five Day-One Questions

### 1. What is the primary data ingestion path?

The primary data ingestion path appears to be through the 'ecom' database, with various raw tables (e.g., 'raw_customers', 'raw_orders', 'raw_items', 'raw_stores', 'raw_products', 'raw_supplies') serving as entry points. These tables are then processed by transformations in the 'models/staging' directory, such as 'stg_customers', 'stg_orders', 'stg_items', 'stg_stores', 'stg_products', and 'stg_supplies'. For example, the 'stg_customers' transformation reads from the 'raw_customers' table in the 'ecom' database (no specific file path or line number available).

### 2. What are the 3–5 most critical output datasets or endpoints?

The 3-5 most critical output datasets or endpoints appear to be the 'customers', 'locations', 'products', 'metricflow_time_spine', and 'orders' tables. These datasets are the final outputs of the transformations and are stored in various locations, such as tables in the database (e.g., 'customers', 'locations', 'products') or files (e.g., 'raw_customers', 'raw_items', 'raw_orders', 'raw_products', 'raw_stores', 'raw_supplies'). For example, the 'models/marts/orders' transformation generates a dataset that provides insights into customer ordering behavior, reading from the 'stg_orders' and 'order_items' tables (no specific file path or line number available).

### 3. What is the blast radius if the most critical module fails?

If the most critical module, 'models/marts/orders', fails, the blast radius would likely affect downstream transformations that rely on the 'orders' dataset, such as 'models/marts/order_items' and 'models/marts/customers'. Additionally, any business intelligence or reporting tools that rely on the 'orders' dataset would also be impacted. For example, the 'models/marts/order_items' transformation reads from the 'orders' table (no specific file path or line number available).

### 4. Where is the business logic concentrated vs. distributed?

The business logic appears to be concentrated in the 'models/staging' and 'models/marts' directories, where transformations are defined to process and refine the data. The 'macros' directory also contains reusable functions, such as 'cents_to_dollars' and 'generate_schema_name', which provide standardized conversions and schema name generation. The business logic is distributed across these directories, with each transformation and macro contributing to the overall data processing pipeline. For example, the 'macros/cents_to_dollars' transformation converts monetary values stored in cents to dollars (no specific file path or line number available).

### 5. What has changed most frequently in the last 90 days?

_Not yet answered_

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
