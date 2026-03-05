# Merch Shipping And Printful

## Checkout source of truth

- Merch shipping now comes from Printful live rates.
- The storefront asks Printful for rates during checkout through `store/printful_fulfillment.py` and `core/services/printful.py`.
- The selected Printful rate is stored on the local `store.Order` in:
  - `printful_shipping_rate_id`
  - `printful_shipping_name`
  - `printful_shipping_cost`
  - `printful_shipping_currency`
- The checkout summary still renders a single shipping line item from `shipping_cost`.
- `shipping_cost` on the local order is the customer-facing amount used in checkout totals.
- For merch orders, `shipping_cost` and `printful_shipping_cost` should match.

## Fulfillment source of truth

- Local payment status gates fulfillment.
- A merch order is submitted to Printful only after local `Order.payment_status` becomes `paid`.
- Card payments trigger submission right after checkout commit.
- Interac e-Transfer orders submit only after staff marks the order paid.
- The fulfillment submit path lives in `store/printful_fulfillment.py`.
- The local order `printful_external_id` is persisted before submission, and retries reconcile against recent Printful orders by that external ID before creating another order.

## Variant mapping source of truth

- Printful merch options are no longer matched by SKU alone.
- `store.ProductOption` now stores:
  - `printful_sync_variant_id` for order submission
  - `printful_variant_id` for live shipping-rate lookups
  - `printful_external_id` for linked external variant references
- `store.Product` stores:
  - `printful_product_id`
  - `printful_external_id`

## Webhook lifecycle

- Printful webhook events are received at `/store/printful/webhook/<secret>/`.
- The endpoint stores a copy of the payload in `store.PrintfulWebhookEvent`.
- After receipt, the app fetches the canonical order payload from Printful and syncs:
  - local Printful status fields
  - tracking numbers / tracking URL
  - shipped state when tracking is present
- Use `python3 manage.py sync_printful_webhook` to register or refresh the webhook subscription for the current environment.

## Operational rules

- Merch and non-merch items must be checked out separately.
- Merch orders are shipping-only; pickup is not offered because Printful fulfills directly to the customer address.
- Checkout only allows full payment now. The deposit path is no longer available to customers.
