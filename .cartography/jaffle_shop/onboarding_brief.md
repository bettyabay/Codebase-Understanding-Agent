# FDE Onboarding Brief
> Generated: 2026-03-12 14:10 UTC

## The Five Day-One Questions

### 1. What is the primary data ingestion path?

{'answer': "The primary data ingestion path appears to be from the 'ecom' database, specifically from tables such as 'raw_customers', 'raw_orders', 'raw_items', 'raw_stores', 'raw_products', and 'raw_supplies'. This can be inferred from the data sources listed, which include 'ecom__raw_customers', 'ecom__raw_orders', 'ecom__raw_items', 'ecom__raw_stores', 'ecom__raw_products', and 'ecom__raw_supplies' (StorageType.TABLE).", 'evidence': 'Data Sources (entry points) - ecom__raw_customers (StorageType.TABLE), ecom__raw_orders (StorageType.TABLE), ecom__raw_items (StorageType.TABLE), ecom__raw_stores (StorageType.TABLE), ecom__raw_products (StorageType.TABLE), ecom__raw_supplies (StorageType.TABLE)'}

### 2. What are the 3–5 most critical output datasets or endpoints?

{'answer': "The 3-5 most critical output datasets or endpoints appear to be 'customers', 'locations', 'products', 'orders', and 'order_items'. These datasets are critical as they provide insights into customer information, store locations, product sales, order details, and order item information. This can be inferred from the data sinks listed, which include 'customers' (StorageType.TABLE), 'locations' (StorageType.TABLE), 'products' (StorageType.TABLE), and the models that generate these datasets, such as 'models/staging/stg_customers', 'models/staging/stg_locations', 'models/staging/stg_products', 'models/marts/orders', and 'models/marts/order_items'.", 'evidence': 'Data Sinks (final outputs) - customers (StorageType.TABLE), locations (StorageType.TABLE), products (StorageType.TABLE), models/staging/stg_customers, models/staging/stg_locations, models/staging/stg_products, models/marts/orders, models/marts/order_items'}

### 3. What is the blast radius if the most critical module fails?

{'answer': "If the most critical module, 'models/staging/stg_products', fails, the blast radius would likely affect downstream modules that rely on the 'products' dataset, such as 'models/marts/orders' and 'models/marts/order_items'. This could impact business functions such as product sales analysis, order fulfillment, and inventory management.", 'evidence': 'models/staging/stg_products, models/marts/orders, models/marts/order_items'}

### 4. Where is the business logic concentrated vs. distributed?

{'answer': "The business logic appears to be concentrated in the 'models' directory, specifically in the 'staging' and 'marts' subdirectories. This is where the data transformations and aggregations are defined, such as renaming and data type conversions in 'models/staging/stg_products', and the generation of order item datasets in 'models/marts/order_items'. The business logic is also distributed across various macros, such as 'macros/cents_to_dollars' and 'macros/generate_schema_name', which provide utility functions for data transformations and schema management.", 'evidence': 'models/staging/stg_products, models/marts/order_items, macros/cents_to_dollars, macros/generate_schema_name'}

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
- `ecom__raw_customers` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_orders` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_items` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_stores` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_products` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\models\staging\__sources.yml`
- `ecom__raw_supplies` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\models\staging\__sources.yml`
- `raw_customers` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\seeds\jaffle-data\raw_customers.csv`
- `raw_items` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\seeds\jaffle-data\raw_items.csv`
- `raw_orders` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\seeds\jaffle-data\raw_orders.csv`
- `raw_products` — `C:\Users\SNFD\Desktop\Tenacious Projects\Codebase-Understanding-Agent\repo_cache\jaffle_shop\seeds\jaffle-data\raw_products.csv`

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
