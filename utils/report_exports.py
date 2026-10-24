"""Excel exports for the ATRIMS-CareMed reports (Chapter IV, Table 15).

Every report honours an inclusive start date and an inclusive end date. The
caller passes timezone-naive datetimes; the end bound is exclusive.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO

import openpyxl
from flask import make_response
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from extensions import db
from models.product import (
    Expense,
    InventoryLog,
    Product,
    Rental,
    TankStatus,
    Transaction,
)

HEADER_FILL = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
HEADER_FONT = Font(name="Arial", size=11, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="Arial", size=14, bold=True, color="0F172A")
SUBTITLE_FONT = Font(name="Arial", size=9, italic=True, color="64748B")
MONEY_FMT = '"₱"#,##0.00'
DATE_FMT = "yyyy-mm-dd"
THIN = Side(style="thin", color="E2E8F0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def parse_range(args):
    """Return (start_dt, end_dt_exclusive) from start_date/end_date query args."""
    start_str = (args.get("start_date") or "").strip()
    end_str = (args.get("end_date") or "").strip()

    start_dt = None
    end_dt = None
    if start_str:
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        except ValueError:
            start_dt = None
    if end_str:
        try:
            end_dt = datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            end_dt = None
    return start_dt, end_dt


def range_label(start_dt, end_dt):
    if not start_dt and not end_dt:
        return "All records"
    start_txt = start_dt.strftime("%b %d, %Y") if start_dt else "Beginning"
    end_txt = (
        (end_dt - timedelta(days=1)).strftime("%b %d, %Y") if end_dt else "Present"
    )
    return f"{start_txt} – {end_txt}"


def _new_sheet(title, headers, subtitle, money_cols=(), date_cols=(), center_cols=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title

    # Title + subtitle block
    ws.append([title])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(len(headers), 1))
    ws.cell(row=1, column=1).font = TITLE_FONT
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="left", vertical="center")

    ws.append([subtitle])
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(len(headers), 1))
    ws.cell(row=2, column=1).font = SUBTITLE_FONT

    ws.append([])
    header_row = 4
    ws.append(headers)
    for col_num, _ in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_num)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER

    return wb, ws, header_row, money_cols, date_cols, center_cols


def _finish_sheet(ws, header_row, headers, rows, money_cols=(), date_cols=(), center_cols=()):
    for row in rows:
        ws.append(row)
        current = ws.max_row
        for idx in money_cols:
            ws.cell(row=current, column=idx).number_format = MONEY_FMT
        for idx in date_cols:
            ws.cell(row=current, column=idx).number_format = DATE_FMT

    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row, max_col=len(headers)):
        for cell in row:
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top")

    for idx in center_cols:
        for row in range(header_row + 1, ws.max_row + 1):
            ws.cell(row=row, column=idx).alignment = Alignment(
                horizontal="center", vertical="top"
            )

    # Totals row for a single money column
    if len(money_cols) == 1:
        total = sum(
            (ws.cell(row=r, column=money_cols[0]).value or 0)
            for r in range(header_row + 1, ws.max_row + 1)
            if isinstance(ws.cell(row=r, column=money_cols[0]).value, (int, float, Decimal))
        )
        ws.append([])
        ws.append(["TOTAL", "", ""] + [""] * (len(headers) - 3))
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        ws.cell(row=ws.max_row, column=money_cols[0]).value = total
        ws.cell(row=ws.max_row, column=money_cols[0]).font = Font(bold=True)
        ws.cell(row=ws.max_row, column=money_cols[0]).number_format = MONEY_FMT

    for col_idx, header in enumerate(headers, 1):
        max_len = len(str(header))
        for row_idx in range(header_row + 1, ws.max_row + 1):
            value = ws.cell(row=row_idx, column=col_idx).value
            max_len = max(max_len, len(str(value or "")))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 3, 12), 48)

    ws.freeze_panes = f"A{header_row + 1}"
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{ws.max_row}"


def xlsx_response(wb, filename):
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return response


# ── Sales ────────────────────────────────────────────────────────────────────
def build_sales_export(start_dt=None, end_dt=None):
    headers = [
        "Reference No", "Date", "Customer", "Fulfillment", "Delivery Fee",
        "Deposit Held", "Total Amount", "Amount Paid", "Balance Due",
        "Payment Status", "Status",
    ]
    query = Transaction.query.filter(Transaction.transaction_type == "Sale")
    if start_dt:
        query = query.filter(Transaction.created_at >= start_dt)
    if end_dt:
        query = query.filter(Transaction.created_at < end_dt)

    rows = []
    for txn in query.order_by(Transaction.created_at.asc()).all():
        rows.append([
            txn.reference_no,
            txn.created_at,
            txn.customer_name or "—",
            txn.fulfillment_type or "—",
            float(txn.delivery_fee or 0),
            float(txn.deposit_amount or 0),
            float(txn.total_amount or 0),
            float(txn.amount_paid or 0),
            float(txn.balance_due or 0),
            txn.payment_status or "—",
            txn.status or "—",
        ])

    wb, ws, header_row, *_ = _new_sheet(
        "Sales", headers, f"ATRIMS-CareMed Sales Report · {range_label(start_dt, end_dt)}"
    )
    _finish_sheet(
        ws, header_row, headers, rows,
        money_cols=(5, 6, 7, 8, 9),
        date_cols=(2,),
        center_cols=(4, 10, 11),
    )
    return wb


# ── Rentals ──────────────────────────────────────────────────────────────────
def build_rentals_export(start_dt=None, end_dt=None):
    headers = [
        "Reference No", "Item", "Qty", "Qty Returned", "Start Date",
        "Expected Return", "Actual Return", "Status", "Rate",
        "Late Fee Incurred", "Customer", "Deposit Held",
    ]
    query = Rental.query.join(Transaction, Rental.transaction_id == Transaction.id)
    if start_dt:
        query = query.filter(Transaction.created_at >= start_dt)
    if end_dt:
        query = query.filter(Transaction.created_at < end_dt)

    rows = []
    for rental in query.order_by(Rental.start_date.asc()).all():
        txn = rental.transaction
        product = rental.product
        rows.append([
            txn.reference_no if txn else "—",
            f"{product.equipment_type} {product.name}" if product else "—",
            rental.quantity or 0,
            rental.quantity_returned or 0,
            rental.start_date,
            rental.expected_return_date,
            rental.actual_return_date,
            rental.status or "—",
            float(rental.monthly_rate or 0),
            float(rental.late_fees_incurred or 0),
            txn.customer_name if txn else "—",
            float(txn.deposit_amount or 0) if txn else 0,
        ])

    wb, ws, header_row, *_ = _new_sheet(
        "Rentals", headers, f"ATRIMS-CareMed Rental Report · {range_label(start_dt, end_dt)}"
    )
    _finish_sheet(
        ws, header_row, headers, rows,
        money_cols=(9, 10, 12),
        date_cols=(5, 6, 7),
        center_cols=(3, 4, 8),
    )
    return wb


# ── Inventory ────────────────────────────────────────────────────────────────
def build_inventory_export(low_only=False):
    headers = [
        "Equipment Type", "Name", "Size", "Condition", "Stock",
        "Reorder Level", "Damaged", "Stock Status", "Unit Cost", "Sale Price",
        "Rent Price", "Rent Period",
    ]
    query = Product.query.filter(Product.status != "Archived")
    if low_only:
        query = query.filter(
            Product.stock <= Product.reorder_level,
            Product.stock > 0,
        )
        title = "Low-Stock"
        subtitle = "ATRIMS-CareMed Low-Stock Report · items at or below reorder level"
    else:
        title = "Inventory"
        subtitle = "ATRIMS-CareMed Inventory Snapshot · current stock on hand"

    rows = []
    for product in query.order_by(Product.equipment_type.asc(), Product.name.asc()).all():
        stock = product.stock or 0
        if stock <= 0:
            stock_status = "Out of Stock"
        elif stock <= (product.reorder_level or 0):
            stock_status = "Low Stock"
        else:
            stock_status = "In Stock"
        rows.append([
            product.equipment_type or "—",
            product.name or "—",
            product.size or "—",
            product.condition or "—",
            stock,
            product.reorder_level or 0,
            product.damaged_stock or 0,
            stock_status,
            float(product.cost_price or 0),
            float(product.sale_price or 0),
            float(product.rent_price or 0),
            product.rent_period or "—",
        ])

    wb, ws, header_row, *_ = _new_sheet(title, headers, subtitle)
    _finish_sheet(
        ws, header_row, headers, rows,
        money_cols=(9, 10, 11),
        center_cols=(5, 6, 7, 8),
    )
    return wb


# ── Tanks ────────────────────────────────────────────────────────────────────
def build_tank_export():
    headers = [
        "Equipment Type", "Name", "Size", "Total Owned", "Full in Stock",
        "Empty in Stock", "Rented Out", "Damaged", "Accounted",
        "Discrepancy",
    ]
    rows = []
    for tank in TankStatus.query.join(Product).filter(Product.status != "Archived").all():
        product = tank.product
        accounted = (
            (tank.full_in_stock or 0)
            + (tank.empty_in_stock or 0)
            + (tank.rented_out or 0)
            + (tank.damaged_in_stock or 0)
        )
        rows.append([
            product.equipment_type or "—",
            product.name or "—",
            product.size or "—",
            tank.total_owned or 0,
            tank.full_in_stock or 0,
            tank.empty_in_stock or 0,
            tank.rented_out or 0,
            tank.damaged_in_stock or 0,
            accounted,
            (tank.total_owned or 0) - accounted,
        ])

    wb, ws, header_row, *_ = _new_sheet(
        "Tank Status",
        headers,
        "ATRIMS-CareMed Oxygen Tank Status · Full / Rented / Empty / Damaged",
    )
    _finish_sheet(ws, header_row, headers, rows, center_cols=range(4, 11))
    return wb


# ── Tank movement log ────────────────────────────────────────────────────────
def build_movements_export(start_dt=None, end_dt=None):
    headers = [
        "Date & Time", "Reference", "Reason Code", "Action", "Equipment",
        "Quantity", "Balance After", "User", "Note",
    ]
    query = InventoryLog.query
    if start_dt:
        query = query.filter(InventoryLog.created_at >= start_dt)
    if end_dt:
        query = query.filter(InventoryLog.created_at < end_dt)

    rows = []
    for log in query.order_by(InventoryLog.created_at.asc()).all():
        product = log.product
        equipment = (
            f"{product.equipment_type} {product.name}" if product else "—"
        )
        rows.append([
            log.created_at,
            log.reference_no or "—",
            log.reason_code or "—",
            log.action or "—",
            equipment,
            log.quantity if log.quantity is not None else "—",
            log.balance_after if log.balance_after is not None else "—",
            log.user_name or "—",
            (log.note or "")[:250],
        ])

    wb, ws, header_row, *_ = _new_sheet(
        "Inventory Movements",
        headers,
        f"ATRIMS-CareMed Stock Movement Log · {range_label(start_dt, end_dt)}",
    )
    _finish_sheet(
        ws, header_row, headers, rows,
        date_cols=(1,),
        center_cols=(6, 7),
    )
    return wb


# ── Supplier reconciliation (Prime Gas) ─────────────────────────────────────
def build_supplier_export(start_dt=None, end_dt=None):
    headers = ["Date", "Prime Gas Batch", "Units Refilled", "Amount Paid", "Recorded By", "Notes"]
    query = Expense.query.filter(Expense.category == "Primegas Refill")
    if start_dt:
        query = query.filter(Expense.date_incurred >= start_dt.date())
    if end_dt:
        query = query.filter(Expense.date_incurred < end_dt.date())

    rows = []
    for expense in query.order_by(Expense.date_incurred.asc()).all():
        rows.append([
            expense.date_incurred,
            expense.expense_title or "—",
            expense.refill_quantity if expense.refill_quantity is not None else "—",
            float(expense.amount or 0),
            expense.recorded_by.full_name if expense.recorded_by else "—",
            (expense.description or "")[:200],
        ])

    wb, ws, header_row, *_ = _new_sheet(
        "Prime Gas Reconciliation",
        headers,
        f"Prime Gas Supplier Reconciliation · {range_label(start_dt, end_dt)} · cutoffs on the 5th and 20th",
    )
    _finish_sheet(
        ws, header_row, headers, rows,
        money_cols=(4,),
        date_cols=(1,),
        center_cols=(3,),
    )
    return wb
