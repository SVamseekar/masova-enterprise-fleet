"""App-wide ops contract: cents, names, forecast series — not demo SQL one-offs."""

from masova_agent.core.ops_contract import (
    CHURN_MIN_ORDERS,
    clamp_po_quantity,
    hydrate_propose_args,
    merge_menu_prices,
    normalize_shift_row,
    public_contract,
    seal_proposal_payload,
    skip_incomplete_propose,
    unit_price_cents,
)


def test_clamp_po_rejects_cover_forecast_as_qty():
    assert clamp_po_quantity(95, 12) == 12
    assert clamp_po_quantity(12, 12) == 12
    assert clamp_po_quantity(None, 12) == 12


def test_skip_campaign_when_churn_read_empty():
    prior = [{"tool": "read_churn_segment", "result": {"ok": True, "customers": [], "count": 0}}]
    out = skip_incomplete_propose(
        "create_draft_campaign",
        {"store_id": "s1", "customer_ids": ["x"]},
        prior,
    )
    assert out["skipped"] is True


def test_public_contract_has_one_churn_rule():
    pub = public_contract()
    assert pub["churn"]["min_orders"] == CHURN_MIN_ORDERS == 2
    assert pub["shift_windows"][0]["start"] == "09:00"
    assert "NOTIFY_MANAGERS" in pub["side_effect_types"]


def test_unit_price_prefers_menu_cents_over_line_total():
    line = {"id": "mi_bbq_chicken", "name": "BBQ Chicken Pizza", "price": 1679, "quantity": 1}
    menu = {"id": "mi_bbq_chicken", "name": "BBQ Chicken Pizza", "price": 1390}
    merged = merge_menu_prices([line], [menu])[0]
    assert merged["unit_price_cents"] == 1390
    assert merged["price"] == 1390


def test_unit_price_divides_line_total_when_qty_gt_1():
    assert unit_price_cents({"price": 2780, "quantity": 2}) == 1390


def test_unit_price_euros_on_order_item():
    assert unit_price_cents({"unit_price": 13.9}) == 1390


def test_seal_forecast_copies_series_from_nested_forecasts():
    sealed = seal_proposal_payload("WRITE_FORECAST", {
        "forecasts": [{
            "predicted_qty": 248,
            "series": [215, 232, 195],
            "series_days": ["2026-08-18", "2026-08-19", "2026-08-20"],
        }],
    })
    assert sealed["series"] == [215, 232, 195]
    assert sealed["predicted_qty"] == 248


def test_canonical_shift_windows():
    row = normalize_shift_row(
        {"staffName": "Ada", "slot": "evening", "date": "2026-08-24"},
        "store-1",
    )
    assert row["startTime"] == "16:00"
    assert row["endTime"] == "23:00"
    assert row["slotName"] == "Evening"


def test_kitchen_brief_seal_parses_metrics():
    sealed = seal_proposal_payload("DRAFT_KITCHEN_BRIEF", {
        "brief_preview": "Kitchen metrics for 2026-08-22: Total Tickets: 293 Average Prep Time: 20.7 Slow Tickets: 117",
    })
    assert sealed["ticket_count"] == "293"
    assert sealed["period_date"] == "2026-08-22"


def test_kitchen_brief_parses_timeline_style_summary():
    sealed = seal_proposal_payload("DRAFT_KITCHEN_BRIEF", {
        "brief_preview": "293 tickets · 20.7 min avg · 117 slow",
    })
    assert sealed["ticket_count"] == "293"
    assert sealed["avg_prep_minutes"] == "20.7"
    assert sealed["slow_tickets"] == "117"


def test_hydrate_kitchen_brief_keeps_tool_counts_when_llm_writes_prose():
    prior = [{
        "tool": "read_kitchen_metrics",
        "result": {
            "ok": True,
            "ticket_count": 293,
            "avg_prep_minutes": 20.7,
            "slow_tickets": 117,
            "period_date": "2026-08-22",
        },
    }]
    out = hydrate_propose_args(
        "draft_kitchen_brief",
        {"store_id": "s1", "brief_text": "Drafting the kitchen coaching brief based on the metrics retrieved for 2026-08-22."},
        prior,
    )
    assert out["ticket_count"] == 293
    assert out["period_date"] == "2026-08-22"


def test_skip_empty_campaign():
    out = skip_incomplete_propose("create_draft_campaign", {"store_id": "s1"})
    assert out["skipped"] is True


def test_hydrate_po_from_low_stock():
    prior = [{
        "tool": "list_low_stock",
        "result": {"ok": True, "items": [{"id": "inv-1", "item_name": "Mozzarella", "primary_supplier_id": "sup"}]},
    }]
    out = hydrate_propose_args("create_draft_po", {"store_id": "s1"}, prior)
    assert out["items"][0]["id"] == "inv-1"
    assert out["supplier_id"] == "sup"
