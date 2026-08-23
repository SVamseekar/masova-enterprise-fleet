"""
Deterministic seed script for MaSoVa Enterprise Fleet (Paris 24-store operator).
Generates data/demo/masova_demo.sqlite with canonical schemas matching platform shared-models
and docs/superpowers/specs/2026-08-22-paris-fleet-scale.md.

Run directly: python scripts/seed_demo_data.py
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    currency TEXT NOT NULL,
    country_code TEXT NOT NULL,
    locale TEXT NOT NULL,
    status TEXT NOT NULL,
    opening_time TEXT NOT NULL,
    closing_time TEXT NOT NULL,
    is_open INTEGER NOT NULL,
    band TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS menu_items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    cuisine TEXT NOT NULL,
    base_price INTEGER NOT NULL,
    discounted_price INTEGER,
    price INTEGER NOT NULL,
    description TEXT,
    spice_level TEXT,
    available INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS inventory (
    id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL REFERENCES stores(id),
    item_code TEXT NOT NULL,
    item_name TEXT NOT NULL,
    current_stock REAL NOT NULL,
    minimum_stock REAL NOT NULL,
    reorder_quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    unit_cost REAL NOT NULL,
    supplier_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    loyalty_points INTEGER NOT NULL DEFAULT 0,
    loyalty_tier TEXT NOT NULL DEFAULT 'BRONZE',
    order_count INTEGER NOT NULL DEFAULT 0,
    total_spent INTEGER NOT NULL DEFAULT 0,
    marketing_consent INTEGER NOT NULL DEFAULT 0,
    primary_store_id TEXT REFERENCES stores(id)
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    order_number TEXT NOT NULL,
    store_id TEXT NOT NULL REFERENCES stores(id),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    customer_name TEXT,
    status TEXT NOT NULL,
    total INTEGER NOT NULL,
    order_type TEXT NOT NULL,
    preparation_time INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    menu_item_id TEXT NOT NULL REFERENCES menu_items(id),
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price INTEGER NOT NULL,
    unit_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL REFERENCES stores(id),
    supplier_id TEXT NOT NULL,
    status TEXT NOT NULL,
    auto_generated INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TEXT NOT NULL,
    approved_by TEXT,
    rejection_reason TEXT
);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id TEXT PRIMARY KEY,
    purchase_order_id TEXT NOT NULL REFERENCES purchase_orders(id),
    inventory_item_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_cost REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL REFERENCES stores(id),
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    target_segment TEXT,
    discount_percent REAL,
    message TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL REFERENCES stores(id),
    order_id TEXT REFERENCES orders(id),
    rating INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reply_text TEXT,
    reply_status TEXT
);

CREATE TABLE IF NOT EXISTS staff (
    id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL REFERENCES stores(id),
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    email TEXT
);

CREATE TABLE IF NOT EXISTS staff_shifts (
    id TEXT PRIMARY KEY,
    store_id TEXT NOT NULL REFERENCES stores(id),
    staff_id TEXT NOT NULL REFERENCES staff(id),
    staff_name TEXT NOT NULL,
    role TEXT NOT NULL,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'CONFIRMED'
);

CREATE TABLE IF NOT EXISTS calendar (
    date TEXT PRIMARY KEY,
    tags_json TEXT NOT NULL
);
"""

# Flagship constants
FLAGSHIP_ID = "68a1f2c9e4b0a1234567890a"
FLAGSHIP_CODE = "DOM011"

STORE_DEFINITIONS = [
    # 6 Large stores (200-240 orders/day, 26-30 staff)
    {"id": FLAGSHIP_ID, "code": "DOM011", "name": "MaSoVa Paris 11e Oberkampf", "city": "Paris", "band": "LARGE"},
    {"id": "68a1f2c9e4b0a12345678914", "code": "DOM020", "name": "MaSoVa Paris 20e Belleville", "city": "Paris", "band": "LARGE"},
    {"id": "68a1f2c9e4b0a1234567890d", "code": "DOM013", "name": "MaSoVa Paris 13e BNF", "city": "Paris", "band": "LARGE"},
    {"id": "68a1f2c9e4b0a12345678900", "code": "DOM010", "name": "MaSoVa Paris 10e République", "city": "Paris", "band": "LARGE"},
    {"id": "68a1f2c9e4b0a12345678912", "code": "DOM018", "name": "MaSoVa Paris 18e Stephenson", "city": "Paris", "band": "LARGE"},
    {"id": "68a1f2c9e4b0a12345678913", "code": "DOM019", "name": "MaSoVa Paris 19e Jaurès", "city": "Paris", "band": "LARGE"},
    # 12 Medium stores (120-160 orders/day, 16-20 staff)
    {"id": "68a1f2c9e4b0a12345678902", "code": "DOM002", "name": "MaSoVa Paris 2e Bourse", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a12345678903", "code": "DOM003", "name": "MaSoVa Paris 3e Marais", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a12345678904", "code": "DOM004", "name": "MaSoVa Paris 4e Bastille", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a12345678905", "code": "DOM005", "name": "MaSoVa Paris 5e Mouffetard", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a12345678906", "code": "DOM006", "name": "MaSoVa Paris 6e Saint-Germain", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a12345678909", "code": "DOM009", "name": "MaSoVa Paris 9e Opéra", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a1234567890c", "code": "DOM012", "name": "MaSoVa Paris 12e Charenton", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a1234567890e", "code": "DOM014", "name": "MaSoVa Paris 14e Sud", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a1234567890f", "code": "DOM015", "name": "MaSoVa Paris 15e Cambronne", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a12345678911", "code": "DOM017", "name": "MaSoVa Paris 17e Batignolles", "city": "Paris", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a12345678915", "code": "DOM021", "name": "MaSoVa Montreuil", "city": "Montreuil", "band": "MEDIUM"},
    {"id": "68a1f2c9e4b0a12345678916", "code": "DOM022", "name": "MaSoVa Saint-Ouen", "city": "Saint-Ouen", "band": "MEDIUM"},
    # 6 Small stores (70-90 orders/day, 10-14 staff)
    {"id": "68a1f2c9e4b0a12345678901", "code": "DOM001", "name": "MaSoVa Paris 1er Louvre", "city": "Paris", "band": "SMALL"},
    {"id": "68a1f2c9e4b0a12345678907", "code": "DOM007", "name": "MaSoVa Paris 7e Saint-Dominique", "city": "Paris", "band": "SMALL"},
    {"id": "68a1f2c9e4b0a12345678908", "code": "DOM008", "name": "MaSoVa Paris 8e Madeleine", "city": "Paris", "band": "SMALL"},
    {"id": "68a1f2c9e4b0a12345678910", "code": "DOM016", "name": "MaSoVa Paris 16e Passy", "city": "Paris", "band": "SMALL"},
    {"id": "68a1f2c9e4b0a12345678917", "code": "DOM023", "name": "MaSoVa Boulogne", "city": "Boulogne-Billancourt", "band": "SMALL"},
    {"id": "68a1f2c9e4b0a12345678918", "code": "DOM024", "name": "MaSoVa Vincennes", "city": "Vincennes", "band": "SMALL"},
]

# 48 SKUs catalogue
SKUS_CATALOGUE = [
    # 20 Pizzas
    ("mi_lg_pizza_pepperoni", "Pepperoni Pizza", "PIZZA", "ITALIAN", 1290, "Classic tomato base, mozzarella, artisan spicy pepperoni", "MILD"),
    ("mi_margherita", "Margherita Pizza", "PIZZA", "ITALIAN", 1090, "San Marzano tomatoes, Fior di Latte mozzarella, fresh basil", "NONE"),
    ("mi_quattro_formaggi", "Quattro Formaggi Pizza", "PIZZA", "ITALIAN", 1390, "Mozzarella, gorgonzola, parmesan, taleggio", "NONE"),
    ("mi_reine", "Pizza Reine", "PIZZA", "ITALIAN", 1250, "Tomato sauce, mozzarella, Paris ham, fresh mushrooms", "NONE"),
    ("mi_calzone", "Calzone Classico", "PIZZA", "ITALIAN", 1320, "Folded pizza with ricotta, ham, mozzarella, tomato", "NONE"),
    ("mi_diavola", "Pizza Diavola", "PIZZA", "ITALIAN", 1350, "Tomato sauce, mozzarella, spianata calabrese, chili oil", "HOT"),
    ("mi_buffalo_mozz", "Buffalo Margherita", "PIZZA", "ITALIAN", 1450, "AOP Campania buffalo mozzarella, cherry tomatoes, pesto", "NONE"),
    ("mi_truffle", "Tartufo Pizza", "PIZZA", "ITALIAN", 1690, "Truffle cream base, mozzarella, wild mushrooms, parmesan", "NONE"),
    ("mi_vegetariana", "Vegetariana", "PIZZA", "ITALIAN", 1190, "Grilled zucchini, roasted bell peppers, aubergines, artichokes", "NONE"),
    ("mi_bbq_chicken", "BBQ Chicken Pizza", "PIZZA", "AMERICAN", 1390, "Smoked chicken breast, red onions, sweet BBQ glaze, mozzarella", "MILD"),
    ("mi_parma", "Prosciutto di Parma Pizza", "PIZZA", "ITALIAN", 1550, "24-month aged Parma ham, rocket, shaved parmesan", "NONE"),
    ("mi_marinara", "Marinara Tradizionale", "PIZZA", "ITALIAN", 950, "San Marzano tomato, wild oregano, fresh garlic, olive oil", "NONE"),
    ("mi_funghi", "Funghi Misti", "PIZZA", "ITALIAN", 1220, "Field mushrooms, thyme, mozzarella, white sauce", "NONE"),
    ("mi_capricciosa", "Capricciosa", "PIZZA", "ITALIAN", 1380, "Ham, mushrooms, artichoke hearts, black olives, mozzarella", "NONE"),
    ("mi_gorgonzola_speck", "Gorgonzola & Speck", "PIZZA", "ITALIAN", 1420, "Creamy gorgonzola, smoked speck, walnut honey", "MILD"),
    ("mi_napolitana", "Napolitana", "PIZZA", "ITALIAN", 1280, "Anchovies, capers, kalamata olives, oregano, tomato", "MILD"),
    ("mi_four_seasons", "Four Seasons", "PIZZA", "ITALIAN", 1360, "Quartered ham, mushrooms, artichokes, olives", "NONE"),
    ("mi_carbonara_pizza", "Pizza Carbonara", "PIZZA", "ITALIAN", 1340, "Guanciale, egg cream, pecorino romano, cracked pepper", "NONE"),
    ("mi_salmon", "Smoked Salmon Pizza", "PIZZA", "ITALIAN", 1590, "Scottish smoked salmon, crème fraîche, dill, capers", "NONE"),
    ("mi_vegan_pesto", "Vegan Pesto Garden", "PIZZA", "ITALIAN", 1290, "House vegan cheese, basil pesto, pine nuts, sun-dried tomatoes", "NONE"),
    # 6 Combos
    ("mi_family_combo", "Family Meal Combo", "COMBO", "ITALIAN", 2890, "2 Large Pizzas, 1 Garlic Bread, 1 1.5L Beverage", "NONE"),
    ("mi_duo_combo", "Duo Pizza Combo", "COMBO", "ITALIAN", 1990, "2 Medium Pizzas, 2 Drinks 33cl", "NONE"),
    ("mi_solo_box", "Solo Box Lunch", "COMBO", "ITALIAN", 1290, "1 Personal Pizza, 1 Side Salad, 1 Drink", "NONE"),
    ("mi_party_pack", "Party Fleet Pack", "COMBO", "ITALIAN", 4990, "4 Large Pizzas, 2 Sides, 4 Drinks", "NONE"),
    ("mi_lunch_special", "Lunch Express Deal", "COMBO", "ITALIAN", 1150, "1 Lunch Pizza or Pasta + Espresso", "NONE"),
    ("mi_late_night", "Late Night Craving Pack", "COMBO", "ITALIAN", 1490, "1 Large Pizza, Mozzarella Sticks, Soft Drink", "MILD"),
    # 6 Sides
    ("mi_garlic_bread", "Garlic Bread with Herbs", "SIDES", "ITALIAN", 490, "Toasted sourdough with garlic butter and rosemary", "NONE"),
    ("mi_mozz_sticks", "Crispy Mozzarella Sticks", "SIDES", "ITALIAN", 650, "6 pieces with marinara dip", "NONE"),
    ("mi_chicken_wings", "Spicy Baked Wings", "SIDES", "AMERICAN", 790, "8 marinated wings with blue cheese sauce", "HOT"),
    ("mi_potato_wedges", "Herbed Potato Wedges", "SIDES", "AMERICAN", 450, "Crispy seasoned wedges with garlic mayo", "MILD"),
    ("mi_caesar_salad", "Classic Caesar Salad", "SIDES", "CONTINENTAL", 750, "Romaine, croutons, parmesan shavings, Caesar dressing", "NONE"),
    ("mi_mixed_greens", "Parisian Green Salad", "SIDES", "CONTINENTAL", 490, "Mesclun greens, cherry tomatoes, shallot vinaigrette", "NONE"),
    # 8 Beverages
    ("mi_espresso", "Espresso Bio", "BEVERAGE", "BEVERAGES", 250, "Single shot organic Italian espresso", "NONE"),
    ("mi_cappuccino", "Cappuccino", "BEVERAGE", "BEVERAGES", 380, "Double shot with creamy steamed milk", "NONE"),
    ("mi_still_water", "Evian Still 50cl", "BEVERAGE", "BEVERAGES", 220, "Mineral water 50cl", "NONE"),
    ("mi_sparkling_water", "San Pellegrino 50cl", "BEVERAGE", "BEVERAGES", 250, "Sparkling mineral water 50cl", "NONE"),
    ("mi_coca_cola", "Coca-Cola 33cl", "BEVERAGE", "BEVERAGES", 290, "Can 33cl", "NONE"),
    ("mi_san_pellegrino_lemon", "San Pellegrino Limonata 33cl", "BEVERAGE", "BEVERAGES", 320, "Citrus sparkling soda", "NONE"),
    ("mi_craft_beer", "Parisian Craft IPA 33cl", "BEVERAGE", "BEVERAGES", 590, "Local craft artisanal beer", "NONE"),
    ("mi_house_wine", "AOP Côtes du Rhône 75cl", "BEVERAGE", "BEVERAGES", 1850, "Full bottle house organic red wine", "NONE"),
    # 8 Desserts & Core Ingredient tracking items
    ("mi_tiramisu", "House Classic Tiramisu", "DESSERT", "DESSERTS", 590, "Savoiardi biscuits, mascarpone cream, espresso, cacao", "NONE"),
    ("mi_panna_cotta", "Panna Cotta Berries", "DESSERT", "DESSERTS", 550, "Vanilla bean cream with raspberry coulis", "NONE"),
    ("mi_cannoli", "Sicilian Cannoli Duo", "DESSERT", "DESSERTS", 520, "Crispy shells with sweet ricotta and pistachio", "NONE"),
    ("mi_nutella_pizza", "Nutella Sweet Pizza", "DESSERT", "DESSERTS", 690, "Warm dough with hazelnut spread and powdered sugar", "NONE"),
    # Core inventory items
    ("ing_mozzarella", "Mozzarella Block 18kg", "INGREDIENT", "ITALIAN", 9200, "Fior di Latte bulk block 18kg", "NONE"),
    ("ing_tomato_base", "Tomato Sauce 12L", "INGREDIENT", "ITALIAN", 4800, "Crushed San Marzano bulk 12L", "NONE"),
    ("ing_flour_25kg", "Tipo 00 Flour 25kg", "INGREDIENT", "ITALIAN", 3600, "Fine Italian pizza flour 25kg", "NONE"),
    ("ing_fresh_basil", "Fresh Basil Crate 1kg", "INGREDIENT", "ITALIAN", 1400, "Fresh organic sweet basil leaves", "NONE"),
]

INVENTORY_TEMPLATES = [
    ("ING-MOZZ-18", "Mozzarella (kg)", "kg", 5.2, "sup_dairy_pt_04"),
    ("ING-TOM-12L", "Tomato Base (L)", "L", 3.8, "sup_tomato_it_01"),
    ("ING-FLOUR-25", "Tipo 00 Flour (kg)", "kg", 1.4, "sup_grain_fr_02"),
    ("ING-BASIL-FRESH", "Fresh Basil (kg)", "kg", 14.0, "sup_herbs_fr_08"),
    ("ING-PEPP-10", "Spicy Pepperoni (kg)", "kg", 8.5, "sup_meat_it_03"),
    ("ING-PARM-5", "Parmigiano Reggiano (kg)", "kg", 18.0, "sup_cheese_it_02"),
    ("ING-HAM-10", "Paris Cooked Ham (kg)", "kg", 7.2, "sup_meat_fr_01"),
    ("ING-MUSH-5", "Field Mushrooms (kg)", "kg", 4.2, "sup_produce_fr_05"),
    ("ING-BUFMOZZ-9", "Buffalo Mozzarella (kg)", "kg", 9.8, "sup_dairy_pt_04"),
    ("ING-GORG-5", "Gorgonzola DOP (kg)", "kg", 11.5, "sup_cheese_it_02"),
    ("ING-OLIVE-5", "Kalamata Olives (kg)", "kg", 6.8, "sup_import_gr_01"),
    ("ING-OIL-10L", "Extra Virgin Olive Oil (L)", "L", 8.2, "sup_import_it_09"),
]

FIRST_NAMES = [
    "Lucas", "Emma", "Gabriel", "Jade", "Louis", "Louise", "Raphaël", "Ambre",
    "Jules", "Alice", "Adam", "Chloé", "Arthur", "Lina", "Hugo", "Mila",
    "Liam", "Rose", "Noah", "Anna", "Paul", "Léa", "Mohamed", "Inès",
    "Julien", "Camille", "Alexandre", "Sarah", "Thomas", "Manon", "Antoine",
    "Marie", "Nicolas", "Émilie", "Maxime", "Léa", "Sébastien", "Juliette",
]

LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit",
    "Durand", "Leroy", "Moreau", "Simon", "Laurent", "Lefebvre", "Michel",
    "Garcia", "David", "Bertrand", "Roux", "Vincent", "Fournier", "Morel",
    "Girard", "André", "Lefevre", "Mercier", "Dupont", "Lambert", "Bonnet",
]


def db_path() -> str:
    return os.getenv("DEMO_DB_PATH") or str(
        Path(__file__).resolve().parents[1] / "data" / "demo" / "masova_demo.sqlite"
    )


def seed(path: str | None = None) -> None:
    target_path = path or db_path()
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target_path)
    rng = random.Random(42)  # Deterministic seed

    try:
        conn.executescript(SCHEMA)

        # Clear existing data for idempotent re-seeding
        tables = [
            "stores", "menu_items", "inventory", "customers", "orders",
            "order_items", "purchase_orders", "purchase_order_items",
            "campaigns", "reviews", "staff", "staff_shifts", "calendar"
        ]
        for t in tables:
            conn.execute(f"DELETE FROM {t}")

        # 1. Insert Stores (24 Paris fleet stores)
        store_rows = []
        for s in STORE_DEFINITIONS:
            store_rows.append((
                s["id"], s["code"], s["name"], s["city"],
                "EUR", "FR", "fr-FR", "ACTIVE",
                "09:00", "22:00", 1, s["band"]
            ))
        conn.executemany("INSERT INTO stores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", store_rows)

        # 2. Insert Menu Items (48 SKUs)
        menu_rows = []
        for idx, sku in enumerate(SKUS_CATALOGUE):
            sku_id, name, cat, cuisine, price, desc, spice = sku
            menu_rows.append((
                sku_id, name, cat, cuisine, price,
                int(price * 0.9) if idx % 5 == 0 else price,
                price, desc, spice, 1
            ))
        conn.executemany("INSERT INTO menu_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", menu_rows)

        # 3. Insert Inventory (24 stores x 48 SKUs = 1,152 inventory rows)
        inv_rows = []
        for s in STORE_DEFINITIONS:
            sid = s["id"]
            band = s["band"]
            for idx, sku in enumerate(SKUS_CATALOGUE):
                sku_id, sku_name, _, _, _, _, _ = sku
                inv_id = f"INV-{s['code']}-{idx:02d}"
                item_code = f"ING-{sku_id.upper()[:10]}"

                # Determine min stock and baseline by band
                if band == "LARGE":
                    min_stock = 25.0
                    base_stock = 35.0
                elif band == "MEDIUM":
                    min_stock = 15.0
                    base_stock = 22.0
                else:  # SMALL
                    min_stock = 8.0
                    base_stock = 12.0

                unit = "kg" if "kg" in sku_name.lower() or "mozz" in sku_name.lower() else ("L" if "sauce" in sku_name.lower() or "water" in sku_name.lower() or "base" in sku_name.lower() else "units")

                # Hero low-stock rows strictly on flagship 11e Oberkampf
                if sid == FLAGSHIP_ID and idx == 0:  # Mozzarella hero
                    item_code = "ING-MOZZ-18"
                    sku_name = "Mozzarella (kg)"
                    current_stock = 6.2
                    min_stock = 10.0
                    unit = "kg"
                elif sid == FLAGSHIP_ID and idx == 1:  # Tomato base hero
                    item_code = "ING-TOM-12L"
                    sku_name = "Tomato Base (L)"
                    current_stock = 3.1
                    min_stock = 6.0
                    unit = "L"
                elif sid == FLAGSHIP_ID:
                    # All other SKUs on flagship are healthy (>= min_stock)
                    current_stock = min_stock + round(rng.uniform(4.0, 15.0), 1)
                else:
                    # Other stores: healthy or occasionally low on a non-hero SKU
                    if idx == (int(s['code'][-2:]) % 40) and idx not in (0, 1):
                        current_stock = round(min_stock * 0.7, 1)  # slightly short
                    else:
                        current_stock = min_stock + round(rng.uniform(2.0, 18.0), 1)

                unit_cost = round(rng.uniform(2.5, 15.0), 2)
                suppliers = (
                    "sup_dairy_fr_04",
                    "sup_produce_fr_05",
                    "sup_grain_fr_02",
                    "sup_import_it_09",
                )
                supplier = suppliers[idx % 4]
                inv_rows.append((
                    inv_id, sid, item_code, sku_name, current_stock,
                    min_stock, min_stock * 1.5, unit, unit_cost, supplier
                ))
        conn.executemany("INSERT INTO inventory VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", inv_rows)

        # 4. Insert 90-day Calendar with required tags
        start_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
        calendar_rows = []
        for d_offset in range(90):
            cur_date = start_date + timedelta(days=d_offset)
            date_str = cur_date.strftime("%Y-%m-%d")
            dow = cur_date.weekday()  # 0=Mon, 6=Sun

            tags = []
            if dow in (4, 5):  # Fri, Sat
                tags.append("weekend_peak")
            elif dow in (1, 2):  # Tue, Wed
                tags.append("weekday_dip")
            else:
                tags.append("dry")

            # Weather tags
            if d_offset % 7 == 2 or d_offset == 80:  # Rain on some days
                tags.append("rain")
            elif d_offset in (45, 46, 47, 75):
                tags.append("heatwave")

            # Holidays
            if date_str == "2026-07-14":  # Bastille day
                tags.append("holiday_peak")
            elif date_str == "2026-08-15":  # 15 août
                tags.append("holiday_quiet")

            # Events
            if d_offset in (12, 33, 62, 82):
                tags.append("event")

            calendar_rows.append((date_str, json.dumps(tags)))
        conn.executemany("INSERT INTO calendar VALUES (?, ?)", calendar_rows)

        # 5. Insert ~35,000 Customers
        customer_rows = []
        customer_count = 35000
        for c_idx in range(1, customer_count + 1):
            cid = f"CUST{c_idx:06d}"
            fn = rng.choice(FIRST_NAMES)
            ln = rng.choice(LAST_NAMES)
            name = f"{fn} {ln}"
            email = f"{fn.lower()}.{ln.lower()}{c_idx % 999}@example.fr"
            phone = f"+336{rng.randint(10000000, 99999999)}"

            # Loyalty distribution: BRONZE / SILVER / GOLD
            tier_roll = rng.random()
            if tier_roll > 0.75:
                tier = "GOLD"
                pts = rng.randint(5000, 20000)
                orders_ct = rng.randint(12, 45)
            elif tier_roll > 0.40:
                tier = "SILVER"
                pts = rng.randint(2000, 4999)
                orders_ct = rng.randint(4, 11)
            else:
                tier = "BRONZE"
                pts = rng.randint(0, 1999)
                orders_ct = rng.randint(1, 3)

            spent = orders_ct * rng.randint(1600, 3200)
            # GDPR: default false, only ~18% opted in
            consent = 1 if rng.random() < 0.18 else 0
            primary_store = STORE_DEFINITIONS[c_idx % 24]["id"]

            customer_rows.append((
                cid, name, email, phone, pts, tier, orders_ct, spent, consent, primary_store
            ))
        conn.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", customer_rows)

        # 6. Insert Orders & Order Items over 14-day window (2026-08-09 to 2026-08-22)
        order_rows = []
        order_item_rows = []
        review_rows = []
        order_counter = 1
        review_counter = 1

        window_start = datetime(2026, 8, 9, tzinfo=timezone.utc)

        # Pre-select active pizza/combo items for fast order item creation
        core_menu_items = [sku for sku in SKUS_CATALOGUE if sku[2] in ("PIZZA", "COMBO", "SIDES", "BEVERAGE")]

        for day_i in range(14):
            day_dt = window_start + timedelta(days=day_i)
            day_str = day_dt.strftime("%Y-%m-%d")

            # Retrieve tags for multipliers
            dow = day_dt.weekday()
            multiplier = 1.0
            if dow in (4, 5):
                multiplier *= 1.35
            elif dow in (1, 2):
                multiplier *= 0.88

            if day_str == "2026-08-15":
                multiplier *= 0.50  # 15 août lull
            elif day_str == "2026-08-20":
                multiplier *= 1.20  # rain multiplier

            for s_idx, store in enumerate(STORE_DEFINITIONS):
                band = store["band"]
                if band == "LARGE":
                    base_orders = int(rng.randint(210, 235) * multiplier)
                elif band == "MEDIUM":
                    base_orders = int(rng.randint(130, 155) * multiplier)
                else:  # SMALL
                    base_orders = int(rng.randint(75, 88) * multiplier)

                for _ in range(base_orders):
                    oid = f"ORD{order_counter:07d}"
                    order_num = f"ORD-{store['code']}-{order_counter:05d}"
                    c_idx = (order_counter * 7 + s_idx) % customer_count
                    cust = customer_rows[c_idx]

                    hour = rng.choices(
                        population=list(range(9, 23)),
                        weights=[2, 3, 8, 14, 12, 4, 3, 4, 9, 16, 18, 12, 6, 2],
                        k=1
                    )[0]
                    minute = rng.randint(0, 59)
                    created_at = f"{day_str}T{hour:02d}:{minute:02d}:00+00:00"

                    # Canonical order statuses
                    if day_i < 13:
                        status = rng.choices(
                            ["DELIVERED", "COMPLETED", "SERVED", "CANCELLED"],
                            weights=[70, 20, 7, 3],
                            k=1
                        )[0]
                    else:
                        status = rng.choices(
                            ["DELIVERED", "PREPARING", "OVEN", "READY", "RECEIVED", "CANCELLED"],
                            weights=[40, 20, 15, 12, 10, 3],
                            k=1
                        )[0]

                    order_type = rng.choice(["DELIVERY", "DELIVERY", "TAKEAWAY", "DINE_IN"])
                    prep_time = rng.randint(12, 28)

                    # Generate ~2.8 order items
                    item_count = rng.choices([1, 2, 3, 4, 5], weights=[15, 30, 35, 15, 5], k=1)[0]
                    order_total = 0

                    for itm_i in range(item_count):
                        item_sku = rng.choice(core_menu_items)
                        sku_id, sku_name, _, _, price, _, _ = item_sku
                        qty = 1 if rng.random() > 0.2 else 2
                        line_total = price * qty
                        order_total += line_total

                        order_item_rows.append((
                            f"ITEM-{order_counter:07d}-{itm_i}",
                            oid, sku_id, sku_name, qty, line_total, round(price / 100.0, 2)
                        ))

                    order_rows.append((
                        oid, order_num, store["id"], cust[0], cust[1],
                        status, order_total, order_type, prep_time, created_at
                    ))

                    # Seed occasional reviews (~1,200 total)
                    if order_counter % 38 == 0:
                        rev_id = f"REV{review_counter:05d}"
                        rating = rng.choices([1, 2, 3, 4, 5], weights=[5, 8, 12, 35, 40], k=1)[0]
                        if rating <= 2:
                            rev_text = rng.choice([
                                "Pizza arrived cold after 45 minutes delay.",
                                "Missing dipping sauce and driver was rude.",
                                "Crust was slightly burnt on the edges.",
                                "Order took over an hour during rush hour.",
                            ])
                        elif rating == 3:
                            rev_text = "Decent pizza, average delivery time."
                        else:
                            rev_text = rng.choice([
                                "Excellent hot pizza, fastest delivery in the 11e!",
                                "Super fresh mozzarella and crispy crust. Loved it.",
                                "Great family meal combo, will order again.",
                                "Best pizza in Paris! Friendly delivery rider.",
                            ])
                        review_rows.append((
                            rev_id, store["id"], oid, rating, rev_text, created_at, None, "UNRESOLVED"
                        ))
                        review_counter += 1

                    order_counter += 1

        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", order_rows)
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?, ?)", order_item_rows)
        conn.executemany("INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)", review_rows)

        # 7. Insert Staff (~480) and Shifts (~6,500)
        staff_rows = []
        shift_rows = []
        staff_counter = 1
        shift_counter = 1

        for store in STORE_DEFINITIONS:
            band = store["band"]
            staff_count = 28 if band == "LARGE" else (18 if band == "MEDIUM" else 12)

            store_staff = []
            for s_num in range(staff_count):
                st_id = f"STAFF{staff_counter:04d}"
                fn = rng.choice(FIRST_NAMES)
                ln = rng.choice(LAST_NAMES)
                st_name = f"{fn} {ln}"

                if s_num == 0:
                    role = "MANAGER"
                elif s_num < int(staff_count * 0.45):
                    role = "KITCHEN_STAFF"
                elif s_num < int(staff_count * 0.70):
                    role = "DRIVER"
                else:
                    role = "CASHIER"

                email = f"{fn.lower()}.{ln.lower()}@masova.fr"
                staff_rows.append((st_id, store["id"], st_name, role, email))
                store_staff.append((st_id, st_name, role))
                staff_counter += 1

            # Generate shifts for 14 days (~6,000–7,000 fleet shifts)
            for day_i in range(14):
                day_dt = window_start + timedelta(days=day_i)
                day_str = day_dt.strftime("%Y-%m-%d")

                for member in store_staff:
                    # Full schedule with peak weekend shifts
                    if rng.random() > 0.08:
                        sh_id = f"SHIFT{shift_counter:06d}"
                        shift_type = rng.choice([("09:00", "16:00"), ("16:00", "23:00"), ("11:00", "19:00")])
                        shift_rows.append((
                            sh_id, store["id"], member[0], member[1], member[2],
                            day_str, shift_type[0], shift_type[1], "CONFIRMED"
                        ))
                        shift_counter += 1
                        # Extra peak weekend shift
                        if day_dt.weekday() in (4, 5) and member[2] == "DRIVER" and rng.random() > 0.6:
                            sh_id2 = f"SHIFT{shift_counter:06d}"
                            shift_rows.append((
                                sh_id2, store["id"], member[0], member[1], member[2],
                                day_str, "18:00", "22:00", "CONFIRMED"
                            ))
                            shift_counter += 1

        conn.executemany("INSERT INTO staff VALUES (?, ?, ?, ?, ?)", staff_rows)
        conn.executemany("INSERT INTO staff_shifts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", shift_rows)

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
    print(f"Successfully seeded demo database at {db_path()}")
