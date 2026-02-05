# Google Sheets Column Structure

This document shows the exact column structure needed for each tab in your spreadsheet.

## Tab: Inventory

**Column Headers (in order):**
1. `product_name`
2. `total_price`
3. `shipping_admin_fee`
4. `total_cost_per_unit`
5. `quantity`
6. `total_bought_quantity`
7. `remaining_qty`
8. `status`
9. `remarks`
10. `date_added`
11. `selling_price`
12. `profit`
13. `tithe`
14. `profit_after_tithe`
15. `date_sold`

**Notes:**
- `total_cost_per_unit` is calculated as: (total_price + shipping_admin_fee) / quantity
- `total_bought_quantity` = original quantity purchased
- `remaining_qty` = automatically updated when items are sold/used/given as freebie
- `quantity` = current quantity (same as remaining_qty)
- `status` can be: in_stock, used, freebie, raffled, sold
- When status is "sold", `selling_price`, `profit`, `tithe`, `profit_after_tithe`, and `date_sold` are populated
- `remaining_qty` decreases automatically when status changes to sold/used/freebie

---

## Tab: Sold Items

**Column Headers (in order):**
1. `product_name`
2. `quantity`
3. `total_cost_per_unit`
4. `selling_price`
5. `total_cost`
6. `profit`
7. `tithe`
8. `profit_after_tithe`
9. `tithe_kept`
10. `remarks`
11. `date_sold`

**Notes:**
- `total_cost` = total_cost_per_unit × quantity
- `profit` = selling_price - total_cost
- `tithe` = profit × 0.10 (10%)
- `profit_after_tithe` = profit - tithe
- `tithe_kept` is a boolean (True/False) to track if tithe has been set aside

---

## Tab: Invoices

**Column Headers (in order):**
1. `invoice_number`
2. `customer_name`
3. `items`
4. `total_amount`
5. `invoice_date`
6. `created_at`

**Notes:**
- `items` stores JSON string with product details: `[{"name": "Product A", "quantity": 2, "price": 100, "subtotal": 200}, ...]`
- `invoice_number` format: INV-YYYYMMDD-{number}
- `total_amount` is in peso (₱)

---

## Tab: Customers

**Column Headers (in order):**
1. `customer_name`
2. `total_orders`
3. `total_spent`
4. `first_order_date`
5. `last_order_date`
6. `products_purchased`

**Notes:**
- `products_purchased` stores JSON string with product summary: `{"Product A": {"qty": 5, "total_amount": 500}, ...}`
- `total_spent` is cumulative across all orders
- `total_orders` counts number of invoices

---

## Tab: INDEX

**Column Headers (in order):**
1. `product_name` (Column A)

**Notes:**
- This tab contains all possible product names
- Used for dropdown selections in the app
- One product name per row in Column A

---

## Tab: Used Freebie

**Column Headers (in order):**
1. `product_name`
2. `quantity`
3. `total_cost_per_unit`
4. `status`
5. `remarks`
6. `date_used`

**Notes:**
- Tracks items that were used or given as freebies
- `status` will be either "used" or "freebie"
- `date_used` = date when item was marked as used/freebie

---

## How to Update Your Spreadsheet

### Option 1: Manual Update
1. Open your spreadsheet: https://docs.google.com/spreadsheets/d/1QpTtcPoTYgd1J9oDi0X1xuS-E5GPiuD1zto0Ger7JCQ/edit
2. For each tab, add/update the column headers as listed above
3. Make sure column order matches exactly

### Option 2: Automated Update (Recommended)
Once your Google credentials are set up in `.env`, run:

```bash
python components/update_spreadsheet_structure.py
```

This will automatically:
- Update all tabs with correct column headers
- Preserve existing data (maps old columns to new columns where possible)
- Create empty tabs with headers if they don't exist

---

## Field Name Changes Summary

**Old → New:**
- `base_price` → `total_price`
- `procurement_fees` → `shipping_admin_fee`
- Calculation: `total_cost_per_unit = (total_price + shipping_admin_fee) / quantity`

**Currency:**
- All amounts are now in peso (₱) instead of dollar ($)

