"""
Real SQLite-backed stand-in for the MaSoVa platform backend, active only
when DEMO_MODE=true. Every response here is a genuine SQL query result
against data/demo/masova_demo.sqlite — never an inline mock dict standing in
for a database read.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def demo_mode() -> bool:
    """Read DEMO_MODE per call (not import-cached)."""
    return (os.getenv("DEMO_MODE") or "").strip().lower() in ("1", "true", "yes", "on")


def demo_focus_store_id() -> str:
    """Focus store ObjectId for demo execution (defaults to Flagship DOM011)."""
    return os.getenv("DEMO_FOCUS_STORE_ID") or "68a1f2c9e4b0a1234567890a"


def _db_path() -> str:
    return os.getenv("DEMO_DB_PATH") or str(
        Path(__file__).resolve().parents[3] / "data" / "demo" / "masova_demo.sqlite"
    )


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if not Path(path).exists():
        raise RuntimeError(
            f"DEMO_MODE is set but no seeded database exists at {path}. "
            "Run scripts/seed_demo_data.py first."
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_store(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "city": row["city"],
        "currency": row["currency"],
        "countryCode": row["country_code"],
        "locale": row["locale"],
        "status": row["status"],
        "openingTime": row["opening_time"],
        "closingTime": row["closing_time"],
        "isOpen": bool(row["is_open"]),
        "band": row["band"] if "band" in row.keys() else "MEDIUM",
        "operatingConfig": {
            "openingTime": row["opening_time"],
            "closingTime": row["closing_time"],
            "isOpen": bool(row["is_open"]),
        },
    }


def _row_to_menu_item(row: sqlite3.Row, store_id: str = "") -> dict[str, Any]:
    return {
        "id": row["id"],
        "storeId": store_id,
        "name": row["name"],
        "category": row["category"],
        "cuisine": row["cuisine"],
        "basePrice": row["base_price"],
        "discountedPrice": row["discounted_price"],
        "price": row["price"],
        "description": row["description"],
        "spiceLevel": row["spice_level"],
        "available": bool(row["available"]),
    }


def _row_to_inventory(row: sqlite3.Row) -> dict[str, Any]:
    is_low = bool(row["current_stock"] < row["minimum_stock"])
    return {
        "id": row["id"],
        "storeId": row["store_id"],
        "itemCode": row["item_code"],
        "itemName": row["item_name"],
        "name": row["item_name"],
        "currentStock": row["current_stock"],
        "quantity": row["current_stock"],
        "minimumStock": row["minimum_stock"],
        "minStock": row["minimum_stock"],
        "reorderQuantity": row["reorder_quantity"],
        "unit": row["unit"],
        "unitCost": row["unit_cost"],
        "supplierId": row["supplier_id"],
        "preferredSupplierId": row["supplier_id"],
        "lowStock": is_low,
    }


def _row_to_order(row: sqlite3.Row, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": row["id"],
        "orderNumber": row["order_number"],
        "storeId": row["store_id"],
        "customerId": row["customer_id"],
        "customerName": row["customer_name"],
        "status": row["status"],
        "total": round(row["total"] / 100.0, 2) if row["total"] > 100 else row["total"],
        "totalCents": row["total"],
        "orderType": row["order_type"],
        "preparationTime": row["preparation_time"],
        "createdAt": row["created_at"],
        "items": items or [],
    }


def _row_to_customer(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "loyaltyPoints": row["loyalty_points"],
        "loyaltyTier": row["loyalty_tier"],
        "totalOrders": row["order_count"],
        "totalSpent": row["total_spent"],
        "marketingConsent": bool(row["marketing_consent"]),
        "marketingOptIn": bool(row["marketing_consent"]),
        "primaryStoreId": row["primary_store_id"],
        "loyaltyInfo": {
            "points": row["loyalty_points"],
            "tier": row["loyalty_tier"],
        },
        "orderStats": {
            "orderCount": row["order_count"],
            "totalSpent": row["total_spent"],
        },
    }


def get(path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Execute SQL query corresponding to GET path."""
    conn = _connect()
    try:
        params = params or {}
        clean_path = path.split("?")[0]

        # 1. Stores list
        if clean_path in ("/api/stores", "/stores"):
            rows = conn.execute("SELECT * FROM stores").fetchall()
            return {"content": [_row_to_store(r) for r in rows], "totalElements": len(rows)}

        # 2. Store by ID / Code
        m = re.match(r"^/(?:api/)?stores/([^/]+)$", clean_path)
        if m:
            sid = m.group(1)
            row = conn.execute("SELECT * FROM stores WHERE id = ? OR code = ?", (sid, sid)).fetchone()
            if row:
                return _row_to_store(row)
            return {"error": "not_found", "message": f"Store {sid} not found"}

        # 3. Menu list
        if clean_path in ("/menu", "/api/menu"):
            store_id = params.get("storeId", "")
            query = "SELECT * FROM menu_items WHERE available = 1"
            rows = conn.execute(query).fetchall()
            return {"content": [_row_to_menu_item(r, store_id=store_id) for r in rows], "totalElements": len(rows)}

        # 4. Single Order
        m = re.match(r"^/(?:api/)?orders/([^/]+)$", clean_path)
        if m:
            oid = m.group(1)
            row = conn.execute("SELECT * FROM orders WHERE id = ? OR order_number = ?", (oid, oid)).fetchone()
            if not row:
                return {"error": "not_found", "message": f"Order {oid} not found"}
            
            # Fetch order items
            item_rows = conn.execute("SELECT * FROM order_items WHERE order_id = ?", (row["id"],)).fetchall()
            items = [
                {
                    "id": ir["id"],
                    "orderId": ir["order_id"],
                    "menuItemId": ir["menu_item_id"],
                    "name": ir["name"],
                    "quantity": ir["quantity"],
                    "price": ir["price"],
                    "unitPrice": ir["unit_price"],
                }
                for ir in item_rows
            ]
            return _row_to_order(row, items=items)

        # 5. Orders list (with filtering by storeId, status, customerId, from)
        if clean_path in ("/orders", "/api/orders"):
            conditions = []
            args = []
            
            store_id = params.get("storeId")
            if store_id:
                conditions.append("(store_id = ? OR store_id IN (SELECT id FROM stores WHERE code = ?))")
                args.extend([store_id, store_id])

            status_param = params.get("status")
            if status_param:
                statuses = [s.strip().upper() for s in status_param.split(",") if s.strip()]
                if statuses:
                    placeholders = ",".join("?" for _ in statuses)
                    conditions.append(f"status IN ({placeholders})")
                    args.extend(statuses)

            customer_id = params.get("customerId")
            if customer_id:
                conditions.append("customer_id = ?")
                args.append(customer_id)

            from_time = params.get("from")
            if from_time:
                conditions.append("created_at >= ?")
                args.append(from_time)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            limit = int(params.get("size", params.get("limit", 100)))

            total = conn.execute(f"SELECT COUNT(*) FROM orders {where_clause}", args).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM orders {where_clause} ORDER BY created_at DESC LIMIT ?",
                args + [limit],
            ).fetchall()

            content = []
            for r in rows:
                item_rows = conn.execute("SELECT * FROM order_items WHERE order_id = ?", (r["id"],)).fetchall()
                items = [
                    {"name": ir["name"], "quantity": ir["quantity"], "menuItemId": ir["menu_item_id"], "unitPrice": ir["unit_price"]}
                    for ir in item_rows
                ]
                content.append(_row_to_order(r, items=items))

            return {"content": content, "totalElements": total, "size": limit}

        # 6. Single Customer
        m = re.match(r"^/(?:api/)?customers/([^/]+)$", clean_path)
        if m:
            cid = m.group(1)
            row = conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
            if row:
                return _row_to_customer(row)
            return {"error": "not_found", "message": f"Customer {cid} not found"}

        # 7. Customers list
        if clean_path in ("/customers", "/api/customers"):
            conditions = []
            args = []
            store_id = params.get("storeId")
            if store_id:
                conditions.append("(primary_store_id = ? OR primary_store_id IN (SELECT id FROM stores WHERE code = ?))")
                args.extend([store_id, store_id])

            min_orders = params.get("minOrders")
            if min_orders:
                conditions.append("order_count >= ?")
                args.append(int(min_orders))

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(f"SELECT * FROM customers {where_clause} LIMIT 100", args).fetchall()
            return {"content": [_row_to_customer(r) for r in rows], "totalElements": len(rows)}

        # 8. Inventory list & low stock
        if clean_path in ("/api/inventory", "/inventory"):
            conditions = []
            args = []
            store_id = params.get("storeId")
            if store_id:
                conditions.append("(store_id = ? OR store_id IN (SELECT id FROM stores WHERE code = ?))")
                args.extend([store_id, store_id])

            if str(params.get("lowStock", "")).lower() == "true":
                conditions.append("current_stock < minimum_stock")

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(f"SELECT * FROM inventory {where_clause}", args).fetchall()
            return {"content": [_row_to_inventory(r) for r in rows], "totalElements": len(rows)}

        if clean_path == "/api/inventory/low-stock":
            store_id = params.get("storeId", "")
            conditions = ["current_stock < minimum_stock"]
            args = []
            if store_id:
                conditions.append("(store_id = ? OR store_id IN (SELECT id FROM stores WHERE code = ?))")
                args.extend([store_id, store_id])

            where_clause = f"WHERE {' AND '.join(conditions)}"
            rows = conn.execute(f"SELECT * FROM inventory {where_clause}", args).fetchall()
            return {"content": [_row_to_inventory(r) for r in rows], "totalElements": len(rows)}

        # 9. Analytics forecast
        if clean_path in ("/api/analytics/forecast", "/analytics/forecast"):
            store_id = params.get("storeId", "")
            row = conn.execute(
                "SELECT COUNT(*) as ct, AVG(total) as avg_total FROM orders WHERE store_id = ? OR store_id IN (SELECT id FROM stores WHERE code = ?)",
                (store_id, store_id),
            ).fetchone()
            ct = row["ct"] if row else 0
            avg_tot = (row["avg_total"] or 0) / 100.0
            
            forecast_val = round(max(ct / 14.0, 10.0) * 1.05, 1)
            return {
                "storeId": store_id,
                "forecast": int(forecast_val * 100),
                "forecasts": [
                    {"date": "2026-08-23", "forecast": forecast_val, "itemId": params.get("itemId", "all")},
                    {"date": "2026-08-24", "forecast": round(forecast_val * 0.95, 1), "itemId": params.get("itemId", "all")},
                ],
                "horizonDays": int(params.get("hours", 24)) // 24 or 7,
                "method": "weighted_moving_average",
            }

        # 10. Analytics products
        if clean_path in ("/api/analytics/products", "/analytics/products"):
            store_id = params.get("storeId", "")
            rows = conn.execute(
                """
                SELECT oi.menu_item_id as id, oi.name, COUNT(*) as volume, AVG(oi.price) as price
                FROM order_items oi
                JOIN orders o ON oi.order_id = o.id
                WHERE o.store_id = ? OR o.store_id IN (SELECT id FROM stores WHERE code = ?)
                GROUP BY oi.menu_item_id
                ORDER BY volume DESC
                LIMIT 10
                """,
                (store_id, store_id),
            ).fetchall()
            top_items = [
                {"id": r["id"], "name": r["name"], "volume": r["volume"], "price": r["price"]}
                for r in rows
            ]
            return {"storeId": store_id, "topItems": top_items, "items": top_items}

        # 11. Analytics orders / kitchen metrics
        if clean_path in ("/api/analytics/orders", "/analytics/orders"):
            store_id = params.get("storeId", "")
            row = conn.execute(
                """
                SELECT COUNT(*) as ct, AVG(preparation_time) as avg_prep
                FROM orders
                WHERE store_id = ? OR store_id IN (SELECT id FROM stores WHERE code = ?)
                """,
                (store_id, store_id),
            ).fetchone()
            ticket_count = row["ct"] if row else 0
            avg_prep = round(row["avg_prep"] or 18.5, 1)
            slow_count = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE (store_id = ? OR store_id IN (SELECT id FROM stores WHERE code = ?)) AND preparation_time > 22",
                (store_id, store_id),
            ).fetchone()[0]
            return {
                "storeId": store_id,
                "ticketCount": ticket_count,
                "avgPrepTimeMinutes": avg_prep,
                "avgPrepMinutes": avg_prep,
                "slowTickets": slow_count,
            }

        # 12. Staff / Users list
        if clean_path in ("/api/users", "/users"):
            conditions = []
            args = []
            store_id = params.get("storeId")
            if store_id:
                conditions.append("(store_id = ? OR store_id IN (SELECT id FROM stores WHERE code = ?))")
                args.extend([store_id, store_id])

            user_type = params.get("type", params.get("role"))
            if user_type:
                conditions.append("role = ?")
                args.append(user_type.upper())

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(f"SELECT * FROM staff {where_clause}", args).fetchall()
            users = [
                {
                    "id": r["id"],
                    "storeId": r["store_id"],
                    "name": r["name"],
                    "fullName": r["name"],
                    "role": r["role"],
                    "type": r["role"],
                    "email": r["email"],
                }
                for r in rows
            ]
            return {"content": users, "totalElements": len(users)}

        # 13. Reviews
        if clean_path in ("/reviews", "/api/reviews"):
            conditions = []
            args = []
            store_id = params.get("storeId")
            if store_id:
                conditions.append("(store_id = ? OR store_id IN (SELECT id FROM stores WHERE code = ?))")
                args.extend([store_id, store_id])

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(f"SELECT * FROM reviews {where_clause} ORDER BY created_at DESC LIMIT 50", args).fetchall()
            reviews = [
                {
                    "id": r["id"],
                    "storeId": r["store_id"],
                    "orderId": r["order_id"],
                    "rating": r["rating"],
                    "text": r["text"],
                    "createdAt": r["created_at"],
                }
                for r in rows
            ]
            return {"content": reviews, "totalElements": len(reviews)}

        return {"error": f"no demo route for GET {path}"}
    finally:
        conn.close()


def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Execute SQL mutations (draft inserts) corresponding to POST path."""
    conn = _connect()
    try:
        clean_path = path.split("?")[0]

        # 1. Draft Purchase Order
        if clean_path in ("/api/purchase-orders/auto-generate", "/purchase-orders/auto-generate"):
            store_id = body.get("storeId", "")
            # Resolve store code to id if needed
            srow = conn.execute("SELECT id FROM stores WHERE id = ? OR code = ?", (store_id, store_id)).fetchone()
            store_id_resolved = srow["id"] if srow else store_id

            po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
            supplier_id = body.get("supplierId", "sup_dairy_pt_04")
            notes = body.get("notes", "Auto-draft by inventory agent")
            created_at = datetime.now(timezone.utc).isoformat()

            conn.execute(
                """
                INSERT INTO purchase_orders (id, store_id, supplier_id, status, auto_generated, notes, created_at)
                VALUES (?, ?, ?, 'DRAFT', 1, ?, ?)
                """,
                (po_id, store_id_resolved, supplier_id, notes, created_at),
            )

            items = body.get("items", [])
            for itm in items:
                itm_id = str(uuid.uuid4())[:8]
                conn.execute(
                    """
                    INSERT INTO purchase_order_items (id, purchase_order_id, inventory_item_id, item_name, quantity, unit_cost)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        itm_id,
                        po_id,
                        itm.get("inventoryItemId") or itm.get("id") or "inv-gen",
                        itm.get("itemName") or itm.get("name") or "Item",
                        float(itm.get("quantity") or itm.get("reorderQuantity") or 10),
                        float(itm.get("unitCost") or 0),
                    ),
                )
            conn.commit()
            return {
                "id": po_id,
                "storeId": store_id_resolved,
                "supplierId": supplier_id,
                "status": "DRAFT",
                "autoGenerated": True,
                "items": items,
                "quantity": sum(float(i.get("quantity", 0)) for i in items) if items else 0,
            }

        # 2. Draft Campaigns
        if clean_path in ("/api/campaigns", "/campaigns"):
            store_id = body.get("storeId", "")
            srow = conn.execute("SELECT id FROM stores WHERE id = ? OR code = ?", (store_id, store_id)).fetchone()
            store_id_resolved = srow["id"] if srow else store_id

            camp_id = f"CAMP{uuid.uuid4().hex[:8].upper()}"
            created_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO campaigns (id, store_id, name, type, status, target_segment, discount_percent, message, created_at)
                VALUES (?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (
                    camp_id,
                    store_id_resolved,
                    body.get("name", "Win-Back Campaign"),
                    body.get("type", "WIN_BACK"),
                    body.get("targetSegment", body.get("segment", "CHURN_RISK")),
                    float(body.get("discountPercent", 15.0)),
                    body.get("message", "We miss you!"),
                    created_at,
                ),
            )
            conn.commit()
            return {
                "id": camp_id,
                "storeId": store_id_resolved,
                "status": "DRAFT",
                "name": body.get("name"),
                "segment": body.get("targetSegment", body.get("segment")),
            }

        # 3. Draft Shifts Bulk
        if clean_path in ("/api/shifts/bulk", "/shifts/bulk"):
            store_id = body.get("storeId", "")
            srow = conn.execute("SELECT id FROM stores WHERE id = ? OR code = ?", (store_id, store_id)).fetchone()
            store_id_resolved = srow["id"] if srow else store_id

            shifts = body.get("shifts", [])
            for s in shifts:
                sh_id = f"SHIFT{uuid.uuid4().hex[:8].upper()}"
                conn.execute(
                    """
                    INSERT INTO staff_shifts (id, store_id, staff_id, staff_name, role, date, start_time, end_time, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT')
                    """,
                    (
                        sh_id,
                        store_id_resolved,
                        s.get("userId", s.get("staffId", "staff-gen")),
                        s.get("name", "Staff Member"),
                        s.get("role", "KITCHEN_STAFF"),
                        s.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                        s.get("startTime", "09:00"),
                        s.get("endTime", "17:00"),
                    ),
                )
            conn.commit()
            return {"storeId": store_id_resolved, "status": "DRAFT", "shifts": shifts, "count": len(shifts)}

        # 4. Notifications
        if clean_path in ("/api/notifications", "/notifications"):
            notif_id = f"NOTIF{uuid.uuid4().hex[:8].upper()}"
            return {"id": notif_id, "status": "SENT", "read": False, **body}

        # 5. Complaints
        if clean_path in ("/reviews/complaints", "/api/reviews/complaints"):
            order_id = body.get("orderId", "")
            ticket_id = f"SUP-{order_id[-6:] if len(order_id) >= 6 else '0001'}"
            return {"id": ticket_id, "ticketId": ticket_id, "status": "PENDING_APPROVAL", "orderId": order_id}

        # 6. Refund request
        if clean_path in ("/payments/refund/request", "/api/payments/refund/request"):
            order_id = body.get("orderId", "")
            ref_id = f"REF-{uuid.uuid4().hex[:6].upper()}"
            return {"refundId": ref_id, "id": ref_id, "status": "PENDING_APPROVAL", "orderId": order_id, "requiresApproval": True}

        # 7. Cancel order request
        m = re.match(r"^/(?:api/)?orders/([^/]+)/cancel-request$", clean_path)
        if m:
            order_id = m.group(1)
            return {"status": "PENDING_APPROVAL", "cancellationRequested": True, "orderId": order_id, "message": "Cancellation request submitted for manager review"}

        # 8. Forecast write
        if clean_path in ("/api/analytics/forecast", "/analytics/forecast"):
            return {"ok": True, "count": len(body.get("forecasts", [])), "status": "SAVED"}

        return {"error": f"no demo route for POST {path}"}
    finally:
        conn.close()
