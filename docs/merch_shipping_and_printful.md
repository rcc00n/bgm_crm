# Merch Shipping And Printful

## Source of truth

- Site checkout owns merch shipping calculation.
- The shipping amount is computed in `store/views.py` inside `checkout()` via `_compute_merch_delivery_cost()`.
- The same checkout flow uses `_recompute_totals_for_form()` to build:
  - `shipping_cost`
  - `order_subtotal`
  - `order_gst`
  - `order_processing`
  - `order_total_with_fees`
- The checkout template renders a single delivery line item in `templates/store/checkout.html` using `shipping_cost`.
- The created `store.Order` stores the same single amount in `shipping_cost`.

## Printful boundary

- `core/services/printful.py` currently syncs catalog/product data only.
- Current Printful usage in this repo is for merch feed/catalog syncing and storefront product mirroring.
- No code currently creates Printful orders.
- No code currently sends recipient/shipping address data to Printful.
- No Printful shipping quote is fetched during checkout.

## Current fulfillment implication

- Merch checkout can collect customer shipping information and save it to the local `Order`.
- Merch checkout can charge the site-configured shipping amount once.
- Automated Printful fulfillment is not wired yet, so the purchase cycle is not fully complete for hands-off fulfillment.
- Until a Printful order submission flow is added, merch fulfillment is manual after checkout.
