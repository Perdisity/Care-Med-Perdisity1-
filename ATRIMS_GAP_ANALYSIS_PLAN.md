# ATRIMS-CareMed — Gap Analysis & Implementation Plan

**Prepared:** 24 Oct 2026
**Source document:** `Perdsity_Chapter1-5_BAM.pdf` (73 pp.) — *Automated Transaction Recording and Inventory Management System for CareMed Medical Supply Enterprise (ATRIMS-CareMed)*
**Target system:** `Perdisity/Care-Med-Perdisity1-` (Flask / SQLAlchemy / MySQL, branch `main` @ `07476fc`)
**Status:** DRAFT for review — no code has been changed for this plan.

---

## 1. Executive summary

The system already implements the **core of the thesis**: point-of-transaction sale/rental recording, stock deduction and restoration, rental locking, tank status tracking, inventory movement logs, low-stock alerts, a searchable transaction list, and one Excel export.

Measured against the thesis's own acceptance criteria:

| Area | Fully met | Partially met | Missing |
|---|---|---|---|
| Functional requirements (FR01–FR10) | 3 | 6 | 1 |
| Automation rules (RULE-01–RULE-10) | 6 | 2 | 2 |
| Functional test cases (TC-01–TC-13) | 9 | 4 | 3 (duplicated by rules above) |

**The six gaps that matter for thesis compliance:**

1. **Deposit is not distance-based** — the thesis makes this part of FR02/RULE-03/TC-03; the code takes a manually typed `customer_deposit`.
2. **Late fees are not computed** — `late_fees` is a free-text number typed by staff; the thesis requires `days overdue × daily rate` (RULE-09/TC-10).
3. **No physical-count adjustment workflow** — stock can only be *increased* via restock; there is no count → variance → reason code → admin approval path (RULE-06/TC-07).
4. **No damaged-return handling** — returns only ask `Full`/`Empty`; no damage reason, damaged status, or damage fee (RULE-10/TC-11).
5. **Reorder level is hard-coded to 5** — the thesis requires a *per-product* reorder level (FR07/RULE-05); `stock <= 5` appears in 4 places.
6. **Cutoff exports are incomplete** — only the transaction list exports; the export route ignores the `start_date`/`end_date` the UI already sends, and sales / rentals / low-stock / tank reports cannot be exported (FR10/TC-12).

Plus three supporting gaps: the movement log has no structured transaction reference (FR08), transaction search has no product filter (FR09), and there is no supplier tank-reconciliation report (FR06).

**Recommended delivery:** 3 phases, ~12–15 dev-days total, additive DB changes only.

---

## 2. What the PDF actually requires

### 2.1 Five functional pillars (§1.5, p. 8)
1. Point-of-transaction recording (sales + rentals, auto totals, reference numbers)
2. Real-time inventory ledger (deduction, restoration, tank status Full/Rented/Empty-For-Refill)
3. Rules engine (balance/stock validation, low-stock thresholds, rental locking)
4. Notifications and alerts (low stock, overdue rentals)
5. Audit and analytics (chronological logs, searchable history, exportable CSV reports)

### 2.2 Functional requirements (Table 4, pp. 21–22)

| ID | Requirement | Priority |
|---|---|---|
| FR01 | Real-time inventory record per product (qty, rental/refill status) | High |
| FR02 | Record a sale on one screen: auto totals, **distance-based rental deposit**, unique reference | High |
| FR03 | Deduct stock on confirmed sale; mark Rented on checkout | High |
| FR04 | Block transactions exceeding available stock | High |
| FR05 | Restore stock on return; refillable items → Empty-For-Refill | High |
| FR06 | Track tank status (Full/Rented/Empty-For-Refill) and **compute refill quantities for supplier reconciliation** | High |
| FR07 | Alert at or below **per-product reorder level** | Medium |
| FR08 | Log every stock change with timestamp, user, **transaction reference**, and **reason** | High |
| FR09 | Search history by reference, customer, **date**, or **product** | High |
| FR10 | Export CSV/Excel reports **per cutoff period**: sales, active rentals, low stock, tank status | High |

### 2.3 Automation rules (Table 7, pp. 27–28)

| ID | Rule | Status today |
|---|---|---|
| RULE-01 | Block over-stock lines | Implemented |
| RULE-02 | Sale deducts stock + movement log | Implemented |
| RULE-03 | Rental locks item + **deposit by delivery distance** | Partial |
| RULE-04 | Return restores stock; tanks → Empty-For-Refill | Implemented |
| RULE-05 | Low-stock alert at **reorder threshold** | Partial (hard-coded) |
| RULE-06 | **Physical-count adjustment + reason code + admin approval** | Missing |
| RULE-07 | Void/cancel reverses stock + reason + audit | Implemented |
| RULE-08 | Partial return restores only returned qty | Implemented |
| RULE-09 | **Overdue fee = days × daily rate** | Missing (manual) |
| RULE-10 | **Damaged return → Damaged status + damage fee** | Missing |

### 2.4 Test cases (Table 18, pp. 55–56)
TC-01 … TC-13, mirrored in §8 below.

### 2.5 Scope boundaries (§1.6, pp. 9–10)
**Out of scope (do not build):** customer self-service portal, native mobile app, barcode/QR scanning, accounting/payroll.
> Note: the current code already has a customer portal, Google OAuth and reviews — more than the thesis requires. Leave it; it is not a compliance risk.

---

## 3. Current-state evidence

| Capability | Where it lives |
|---|---|
| Product stock + status + condition | `models/product.py:6-32` |
| Tank status (total / rented / full / empty) | `models/product.py:39-54` |
| Rental (dates, rate, deposit, quantity returned, late fees field) | `models/product.py:438-470` |
| Rental invoices (monthly, recurring) | `models/product.py:569-597`, `generate_monthly_invoices.py` |
| Inventory movement log | `models/product.py:600-613` |
| Sale recording (single screen, ref no, stock lock) | `admin_routes.py:1583-1830` |
| Rental recording (lock, invoices, deposit field) | `admin_routes.py:1836-2268` |
| Return (partial, tank empty/full restore) | `admin_routes.py:3157-3284` |
| Cancel/void with restock + reason | `admin_routes.py:2513-2600` |
| Stock update (increase only) | `admin_routes.py:1419-1534` |
| Transaction search + date filter | `admin_routes.py:2316-2512` |
| Excel export (transactions only) | `admin_routes.py:2690-2788` |
| Reports analytics | `admin_routes.py:3537+`, `templates/admin/reports.html` |
| Dashboard low-stock + tank summary | `admin_routes.py:324-333`, `4834` |
| STAFF RBAC | `admin_routes.py:60` + `models/users.py:69-86` |
| Daily backup scheduler | `app.py:253-267`, `utils/backup.py` |

---

## 4. Traceability matrix

### 4.1 Functional requirements

| ID | Status | Evidence | Gap |
|---|---|---|---|
| FR01 | ✅ Met | `Product.stock/status`, `TankStatus` | — |
| FR02 | ⚠️ Partial | Ref no + totals at `admin_routes.py:1662`, `1976`; deposit typed manually at `1872-1890`, `1990` | No distance field, no tier rule |
| FR03 | ✅ Met | `1725-1746` (sale), `2070-2086` (rental) | — |
| FR04 | ✅ Met | `1725-1728`, `2065-2078`, `3315-3317` | — |
| FR05 | ✅ Met | `3209-3230` | — |
| FR06 | ⚠️ Partial | `TankStatus` + `empty_in_stock` drives refill (`3315`) | No supplier/cutoff reconciliation report |
| FR07 | ⚠️ Partial | Alert exists, but `stock <= 5` hard-coded at `327`, `1118`, `3635`, `4834` | No `reorder_level` per product |
| FR08 | ⚠️ Partial | `InventoryLog` has timestamp/user/note | No `transaction_id`, `reference_no`, `reason_code` columns; ref only embedded in free text |
| FR09 | ⚠️ Partial | `2343-2348` covers ref, customer, landmark, serial | No product filter, no combined date+product search |
| FR10 | ⚠️ Partial | XLSX export at `2690-2788` | `start_date`/`end_date` sent by UI (`transactions.html:114`) but **ignored** by route; no sales/rental/low-stock/tank exports |

### 4.2 Rules

| ID | Status | Evidence | Gap |
|---|---|---|---|
| RULE-01 | ✅ | `1725`, `2075`, `2065` | — |
| RULE-02 | ✅ | `1732`, `1773-1780` | — |
| RULE-03 | ⚠️ | `2000` row lock, `2070` tank lock | Deposit not distance-based |
| RULE-04 | ✅ | `3212-3218` | — |
| RULE-05 | ⚠️ | `327`, `4834` | Hard-coded threshold |
| RULE-06 | ❌ | `update_stock` only increments (`1443-1447`) | No adjustment/approval workflow |
| RULE-07 | ✅ | `2513-2600` requires reason, restocks, logs | Audit log is deletable (see §5 G-10) |
| RULE-08 | ✅ | `3196-3205` | — |
| RULE-09 | ❌ | `3164-3177` reads a typed amount | No due-date math, no daily rate |
| RULE-10 | ❌ | `3207` only `Full`/`Empty` | No damaged status/fee |

### 4.3 Test cases

| TC | Scenario | Today |
|---|---|---|
| TC-01 | Over-stock blocked | ✅ |
| TC-02 | Sale deducts + logs | ✅ |
| TC-03 | Rental locks + deposit matches distance rule | ⚠️ lock yes, deposit manual |
| TC-04 | Two staff rent same item | ⚠️ `with_for_update()` on MySQL; **no test**, no-op on SQLite |
| TC-05 | Return tank → Empty-For-Refill | ✅ |
| TC-06 | Low-stock at reorder threshold | ⚠️ threshold fixed at 5 |
| TC-07 | Count variance needs reason + approval | ❌ |
| TC-08 | Void reverses stock + reason in audit | ✅ |
| TC-09 | Partial return | ✅ |
| TC-10 | Overdue fee = days × rate | ❌ |
| TC-11 | Damaged return → Damaged + fee | ❌ |
| TC-12 | Cutoff export matches ledger | ⚠️ only transactions, no cutoff filter |
| TC-13 | Search by ref/customer/date/product | ⚠️ no product filter |

### 4.4 Thesis modules vs. implementation

| Thesis module | Status |
|---|---|
| M1 Real-Time Inventory Ledger | ⚠️ built, but threshold + structured movement ref missing |
| M2 Transaction Recording Engine | ⚠️ built, but deposit rule + damage/late rules missing |
| M3 Alerts & Notifications | ⚠️ low-stock + overdue present; supplier refill report missing |
| M4 Reporting & Audit | ⚠️ dashboard built; export coverage and immutability gaps |

---

## 5. Detailed gaps and proposed fixes

### G-01 — Per-product reorder level (FR07, RULE-05, TC-06)
**Current:** `Product.stock <= 5` hard-coded in dashboard (`admin_routes.py:327`), product list (`1118`), reports (`3635`), notifications (`4834`). Reports also exclude `stock = 0`.
**Change:**
- Add `Product.reorder_level` (`Integer`, default `5`, not null).
- Replace all four queries with `Product.stock <= Product.reorder_level`.
- Show the field in Add/Edit Product; allow 0 = alerts disabled? (decide in review).
- Include zero-stock products in the reorder report.

**Acceptance:** set reorder = 10, stock = 9 → dashboard badge, notification, report and product filter all flag it; stock = 10 → no flag.
**Files:** `models/product.py`, `routes/admin_routes.py`, `templates/admin/products.html`, `templates/admin/reports.html`, `templates/modals/rent_purch_modal.html` (display only), migration.
**Effort:** 0.5–1 day.

### G-02 — Automatic late fee (RULE-09, TC-10)
**Current:** `late_fees` is typed by staff on the return form (`admin_routes.py:3164-3177`); no calculation, no rate configuration.
**Change:**
- Add a `SystemSetting` key `late_fee_per_day` (default value to confirm, e.g. ₱100).
- On return: `days_overdue = max(0, (return_date - expected_return_date).days)`.
- `computed_fee = days_overdue × rate × qty_returned` (or per rental — confirm).
- Pre-fill the return form; a manual override requires a permission (`can_override_fees`) and a reason, logged.
- Persist to `Rental.late_fees_incurred` and create `Payment(payment_type="Late Fee")`.

**Acceptance:** return 3 days late at ₱100/day → ₱300 on the statement and in the audit log.
**Files:** `routes/admin_routes.py:3157-3284`, `templates/admin/transaction_details.html:559`, settings model/UI, migration.
**Effort:** 0.5–1 day.

### G-03 — Distance-based deposit (FR02, RULE-03, TC-03)
**Current:** no occurrence of "distance" anywhere in the Python code; `customer_deposit` is free input (`1872-1890`) and stored directly (`1990`).
**Change:**
- Add `Transaction.distance_km` (`Numeric(6,2)`) and `Transaction.deposit_rule` (tier label).
- Configure tiers in `SystemSetting` (e.g. 0–3 km, 3–6 km, >6 km — **values needed from you**).
- Compute server-side at rental creation; display the breakdown in the rent modal.
- Manual override requires permission + reason; log the override in `SecurityLog`.

**Acceptance:** TC-03 — deposit equals the tier for the entered distance; 4.5 km with a 3–6 km tier gives the tier value.
**Files:** `models/product.py` (Transaction), `routes/admin_routes.py:1836-1990`, `templates/modals/rent_purch_modal.html`, migration.
**Effort:** 1–1.5 days.

### G-04 — Link movement logs to transactions (FR08)
**Current:** `InventoryLog` has `action`, `quantity`, `note`, `user_id`, `user_name`, `created_at` (`models/product.py:600-613`). Transaction refs appear only inside `note` text.
**Change:**
- Add `transaction_id` (FK, nullable), `reference_no` (`String(40)`), `reason_code` (`String(30)`), `balance_after` (`Integer`).
- Populate on every write: sale (`1773`), rental (`2113`), return (`3232`), restock (`1477`), cancel (`2545/2565/2580`), refill, adjustment.
- Add a filter/export by reference and reason.
- Backfill old rows is optional (leave null; note text remains).

**Acceptance:** every stock movement row can be filtered by `TRX/RNT/PUR` reference and reason code; joining to the transaction works.
**Files:** model + all write sites + `templates/admin/system_logs.html`, migration.
**Effort:** 0.5–1 day.

### G-05 — Cutoff report exports (FR10, TC-12)
**Current:** one endpoint, transactions only, and **it ignores `start_date`/`end_date`** even though `templates/admin/transactions.html:114` sends them.
**Change:**
- Honour the date range in `export_transactions`.
- Add exports: sales summary, active/overdue rentals, low stock/reorder, tank status.
- Either four endpoints or a single workbook with four sheets; include a header with the cutoff period and generated-by user.
- Offer XLSX (existing) and CSV.
- Add export buttons to `templates/admin/reports.html` and the inventory page (the current "Export Log" is only `window.print`).

**Acceptance:** TC-12 — for a chosen period, exported rows equal the on-screen ledger; filenames include the period.
**Files:** `routes/admin_routes.py`, `templates/admin/reports.html`, `templates/admin/products.html`, `templates/admin/transactions.html`.
**Effort:** 1–1.5 days.

### G-06 — Physical-count adjustment with approval (RULE-06, TC-07)
**Current:** `update_stock` accepts only `increment > 0` (`1439-1447`) and immediately commits; no variance, no reason code enforcement, no approval.
**Change:**
- New model `StockAdjustment`: `product_id`, `system_qty`, `counted_qty`, `delta`, `reason_code`, `notes`, `status` (`Pending/Approved/Rejected`), `requested_by/at`, `reviewed_by/at`, `review_notes`.
- Staff screen: enter counted qty + reason → creates a Pending request (no stock change).
- Admin screen: approve → apply delta atomically, update `Product.stock`, `TankStatus`, write `InventoryLog(action="ADJUSTMENT", reason_code=...)`; reject → no change.
- Permission: `can_approve_adjustments` (admin only by default).
- Show pending count on the dashboard.

**Acceptance:** TC-07 — no adjustment can change stock without a reason code and an approval; both steps are in the audit trail.
**Files:** new model, `routes/admin_routes.py`, `templates/admin/products.html` (or new `inventory.html`), `models/users.py` (permission), migration.
**Effort:** 1.5–2 days.

### G-07 — Damaged return (RULE-10, TC-11)
**Current:** return form only asks `Full`/`Empty` per item (`3207`); no condition, no fee.
**Change:**
- Per returned item: `Good` / `Damaged` + damage reason + fee.
- Add `TankStatus.damaged_in_stock` (and for non-tanks set `Product.condition = "Damaged"` / a non-sellable status).
- Damaged units are **not** returned to available stock.
- `Payment(payment_type="Damage Fee")`, optionally deducted from the held deposit (`CustomerDeposit`).
- Reason code is mandatory; both the fee and status change go to the audit log.

**Acceptance:** TC-11 — damaged return sets a Damaged status, excludes the unit from availability, and records the fee.
**Files:** `models/product.py`, `routes/admin_routes.py:3157-3284`, `templates/admin/transaction_details.html`, migration.
**Effort:** 1–1.5 days.

### G-08 — Search completeness (FR09, TC-13)
**Current:** transaction search covers reference, customer name, landmark and rental serial (`2343-2348`) plus date range (`2331-2366`). No product filter.
**Change:** add an `outerjoin(Purchase)` and product name/asset-tag filter; add a product dropdown; keep date range. Optionally add a single "history" search across transactions + movement logs.

**Acceptance:** TC-13 — searching a product name returns every transaction containing it; combined with a date range returns only that window.
**Files:** `routes/admin_routes.py:2316-2512`, `templates/admin/transactions.html`.
**Effort:** 0.5 day.

### G-09 — Supplier tank reconciliation report (FR06)
**Current:** `TankStatus` tracks full/rented/empty; `process-primegas` (`3287-3335`) flips empty → full and books an expense, but there is no supplier-facing report.
**Change:** add a report (and export) per tank size/model at cutoff: total owned, full, rented, empty, damaged, plus refill batches for the period with quantities and costs, and a reconciliation line against PrimeGas records.

**Acceptance:** for the 5th/20th cutoff the report totals reconcile with the sum of refill batches.
**Files:** `routes/admin_routes.py`, `templates/admin/reports.html`.
**Effort:** 1 day.

### G-10 — Audit immutability (non-functional: "permanent audit log", p. 23)
**Current:** admins can delete security logs (`/security/delete-log`, `/security/clear-logs`, `admin_routes.py:4567-4595`).
**Change:** restrict hard deletes (archive/soft-delete or admin-only with a written reason), and never delete `InventoryLog`. Document retention.

**Acceptance:** no endpoint silently removes an audit row; deletions, if kept, are themselves logged.
**Effort:** 0.5 day.

### G-11 — Concurrency guarantee (TC-04)
**Current:** `with_for_update()` at `1713` and `2000` works on MySQL/InnoDB but is a **no-op on SQLite** (your local dev DB), and there is no test.
**Change:** make the deduction atomic independently of the DB:
`Product.query.filter(Product.id == id, Product.stock >= qty).update({Product.stock: Product.stock - qty})` and check `rowcount == 1`, or keep the row lock and add a MySQL integration test. Add the two-thread test.

**Acceptance:** two concurrent rental requests for the last unit → exactly one succeeds, the other gets the "insufficient stock" message.
**Effort:** 0.5–1 day (plus test).

---

## 6. Data model changes (summary)

| Table | Column | Type / default | Purpose |
|---|---|---|---|
| `product` | `reorder_level` | Integer, default 5 | G-01 |
| `transaction` | `distance_km` | Numeric(6,2), null | G-03 |
| `transaction` | `deposit_rule` | String(30), null | G-03 |
| `inventory_logs` | `transaction_id` | Integer FK, null | G-04 |
| `inventory_logs` | `reference_no` | String(40), null, indexed | G-04 |
| `inventory_logs` | `reason_code` | String(30), null | G-04 |
| `inventory_logs` | `balance_after` | Integer, null | G-04 |
| `tank_status` | `damaged_in_stock` | Integer, default 0 | G-07 |
| `stock_adjustment` | *(new table)* | — | G-06 |
| `system_setting` | *(new table: key, value, data_type, updated_by, updated_at)* | — | G-02, G-03 |

**Migration warning:** `flask db upgrade` **cannot build a fresh database** — the chain fails at `ALTER TABLE users ... no such table: users` because the early migrations assume existing tables. Any new migration must be added to the existing chain for the production MySQL DB, and a separate baseline (SQL dump or `create_all` + `stamp head`) is needed for fresh installs. Plan for this explicitly in Phase 3.

---

## 7. Phased implementation plan

### Phase 1 — Compliance-critical (P0) · ~4–5 days
| # | Item | Effort |
|---|---|---|
| 1.1 | Settings foundation: `SystemSetting` + admin settings screen (late rate, deposit tiers, damage fee defaults) | 1 d |
| 1.2 | G-01 per-product reorder level (schema, queries, UI) | 0.5–1 d |
| 1.3 | G-02 auto late fee | 0.5–1 d |
| 1.4 | G-03 distance-based deposit | 1–1.5 d |
| 1.5 | G-04 transaction-linked movement log | 0.5–1 d |
| 1.6 | G-05 cutoff exports + fix ignored date filter | 1–1.5 d |

> 1.1 is first because 1.2–1.4 read their values from it.

### Phase 2 — Workflow gaps (P1) · ~4–5 days
| # | Item | Effort |
|---|---|---|
| 2.1 | G-06 physical-count adjustment + approval | 1.5–2 d |
| 2.2 | G-07 damaged return + fee | 1–1.5 d |
| 2.3 | G-08 product/date search | 0.5 d |
| 2.4 | G-09 supplier tank reconciliation report | 1 d |

### Phase 3 — Hardening (P2) · ~3 days
| # | Item | Effort |
|---|---|---|
| 3.1 | G-11 concurrency test + atomic stock update | 1 d |
| 3.2 | G-10 audit immutability | 0.5 d |
| 3.3 | Automated tests for TC-01…TC-13 (pytest + test client) | 1.5 d |
| 3.4 | Migration baseline for fresh installs + docs | 0.5–1 d |

---

## 8. Test plan (maps to Table 18)

| TC | Test to automate | Type |
|---|---|---|
| TC-01 | POST sale with qty > stock → 302 + flash, stock unchanged | route test |
| TC-02 | POST sale qty 2 → stock −2, `InventoryLog` row with ref | route + DB |
| TC-03 | POST rental at 4.5 km → deposit equals tier; item locked | route |
| TC-04 | Two threads rent last unit → one 200, one rejection | MySQL integration |
| TC-05 | Return tank as Empty → `empty_in_stock +1`, `rented_out −1` | route |
| TC-06 | Set reorder 10 / stock 9 → alert present; stock 10 → absent | unit |
| TC-07 | Adjustment without reason → 400; with reason unapproved → stock unchanged; approved → delta applied | route |
| TC-08 | Cancel with reason → stock restored, reason stored | route |
| TC-09 | Return 1 of 3 → qty_returned 1, status Partially Returned, 2 still locked | route |
| TC-10 | 3 days overdue at ₱100 → fee ₱300 | unit |
| TC-11 | Return Damaged → status Damaged, not available, fee recorded | route |
| TC-12 | Export for period → row count and totals equal ledger | route + file parse |
| TC-13 | Search by product + date → exact set | route |

Existing test infrastructure: **none** (no `tests/`, no pytest in `requirements.txt`). Add `pytest`, `pytest-flask` as dev dependencies (do not ship them in the production image, or keep in `requirements-dev.txt`).

---

## 9. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Deposit tiers / late rate unknown | Phase 1 blocked | Get the real values before coding (see §10) |
| Live MySQL data | Migration could break production | Additive columns only, nullable, with defaults; test on a dump |
| Existing transactions lack distance | Reports show null | Do not backfill; apply rule to new rentals only, flag old ones |
| SQLite dev vs MySQL prod differences (`with_for_update`, `date_format`) | Tests pass locally, fail in prod | Run TC-04 and report/export tests against MySQL |
| Staff resistance to approval step | Workflow slowdown | Permission `can_approve_adjustments` can be granted to senior staff |
| Fee disputes | Customer friction | Show computed fee and rate on the statement; keep override + reason |
| Reports slow as data grows | UX | Index `created_at`, `reference_no`; paginate exports by period |

---

## 10. Open questions (need your decision before coding)

1. **Deposit tiers** — what distance bands and amounts? (e.g. 0–3 km ₱500, 3–6 km ₱1,000, >6 km ₱1,500?) Is the deposit per transaction or per item?
2. **Late fee** — amount per day, and is it per rented unit or per rental? Does it start the day after `expected_return_date`?
3. **Damage fee** — fixed schedule, percentage of deposit, or manual assessment within a cap?
4. **Approval authority** — admin only, or any staff with a new permission?
5. **Production data** — is the MySQL DB live with real transactions? (Determines whether we can add NOT NULL columns and whether we backfill.)
6. **Reorder level default** — 5 as today, or a per-category default?
7. **Exports** — one multi-sheet workbook or separate files per report?
8. **Customer portal** — it is out of thesis scope but already built; keep as-is (recommended) or hide for the defense?

---

## 11. Out of scope (per §1.6)

- Customer self-service portal enhancements
- Native iOS/Android app
- Barcode/QR scanning
- Accounting/tax/payroll
- SMS/push notifications

---

## 12. Definition of done

- [ ] All FR01–FR10 met, each with a test from §8.
- [ ] All RULE-01–RULE-10 enforced server-side (not only in the UI).
- [ ] TC-01…TC-13 automated and green.
- [ ] Every stock change carries user, timestamp, reference and reason.
- [ ] Cutoff exports (sales, rentals, low stock, tank status) reconcile with the ledger.
- [ ] Per-product reorder levels editable without code changes.
- [ ] Fresh-install DB path documented and working.
- [ ] No audit rows can be silently deleted.

---

## 13. Implementation status (24 Oct 2026)

**Status:** Implemented and committed on `main`; push pending owner approval.

### 13.1 Delivered

| Gap | Implementation |
|---|---|
| Distance-based / flat delivery deposit | Delivery rentals capture `distance_km`, ignore the typed deposit, and apply the owner-set flat deposit (`SystemSetting.deposit_flat_amount`, default ₱1,500). `Transaction.deposit_rule` records which rule was used. |
| Automatic late fees | On return: `days overdue × units returned × late_fee_per_day`. Stored on `Rental.late_fees_incurred` and as a `Late Fee` payment. A positive manual amount is accepted only from an Administrator and writes a `SecurityLog` override entry. |
| Physical-count adjustments | `/admin/adjustments`: staff/custodian submits counted quantity + reason code; Administrator approves or rejects. Approval applies the variance and writes an `ADJUSTMENT` movement with reference `ADJ-00001`. |
| Damaged-return workflow | Return form captures Good / Minor / Major / Total Loss per item. Minor = 25%, major = 50% of the held deposit (configurable); total loss = cash price. Units move to `damaged_stock` / `TankStatus.damaged_in_stock` and are excluded from rentable stock. Damage fee is deducted from the deposit refund. |
| Per-product reorder level | `Product.reorder_level` editable in Add/Edit forms; system default in settings. Dashboard, products list, reports, notifications and exports all use `stock <= reorder_level`. |
| Cutoff exports | `/admin/reports/export/<type>` for sales, rentals, inventory, low stock, tanks, movements and Prime Gas; `/admin/transactions/export` now honours `start_date`/`end_date`. Reports page has 1st–5th, 6th–20th, 21st–end presets. |
| Void approval | Staff cancellation creates a `VoidRequest`; stock is untouched until an Administrator approves it at `/admin/void-requests`. Administrators can cancel directly. Every applied void writes reference-linked restock logs. |
| Product search (FR09) | Transaction list and Excel export search reference, customer, landmark, tank serial number, product name, and equipment type. |
| Supplier quantities (FR06) | Prime Gas batches store `Expense.refill_quantity`; the supplier reconciliation export shows units refilled, amount paid, recorder, and notes. |
| Transaction-linked audit trail | `InventoryLog` gained `transaction_id`, `reference_no`, `reason_code`, `balance_after`. Sale, rental, return, restock, refill, void and adjustment writes fill them. Product history modal and `/admin/inventory-movements` show reference, reason, user, time and balance. |
| Role presets | Owner/Admin, Counter Staff, Inventory Custodian and Delivery Personnel presets; existing per-user permission checkboxes still override them. |
| Editable rules | `/admin/settings` (Administrator only) edits deposit, late fee, damage percentages and default reorder level without code changes. |

### 13.2 Verification performed

- Local schema recreated with `db.create_all()` against SQLite (`instance/dev.db`).
- **32/32** Phase 1 checks passed: login, all admin pages, settings save, sale, delivery rental (₱1,500 deposit + 5.5 km), auto late fee (₱1,900), return, all seven exports and date-filtered transaction export.
- **55/55** Phase 2 checks passed: major-damage return (₱750 fee, ₱750 net refund), total-loss return (cash-price fee, no stock restoration, deposit forfeited), tank rental → empty return → Prime Gas refill (quantity stored), tank physical count based on full-in-stock, staff void → admin approval, custodian count → admin approval, transaction search by product, movement-log filters and product-history API.
- **10/10** settings/role checks passed: Inventory Custodian preset permissions, owner-editable deposit/late-fee values, and a new rental using the updated ₱1,800 deposit.
- `python -m py_compile` clean for all changed Python modules; `flask db heads` shows a single head (`a7c1e9f0b2d4`).

### 13.3 Local reset / run

```bash
# Activate the venv, then recreate the dev schema and seed accounts/products:
python <temp>/reset_caremed_db.py     # local-only helper, not committed
flask db stamp head                   # mark the create_all schema as current
python app.py                         # http://127.0.0.1:5000
```

`flask db upgrade` is **not** a fresh-install path for this repository: the historical migration chain has no initial "create users/product" revision. Fresh installs must use `db.create_all()` (or the provided reset helper) and then `flask db stamp head`; migrations from `84cb0ad52ee2` onward apply to databases that already contain the original schema.

### 13.4 Still open / deliberately deferred

- ~~Search *transactions* by product name (FR09)~~ — implemented in the transaction list and export.
- Customer-facing portal, Google OAuth and email OTP remain outside thesis scope and were left untouched.
- Multi-sheet single-workbook export (current implementation produces one file per report).
- Automated pytest suite is not in the repo; the three verification scripts live in the temp workspace.
