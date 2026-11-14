"""Seeded synthetic retail world: 6 users with gift-card balances, 8 orders.

Everything is invented. Run `python3 world/seed_world.py` to (re)write
users.json and orders.json. The seed is fixed, so the output is identical on
every run.

Money is in dollars with two decimals.
"""
import json
import pathlib
import random

SEED = 4417
HERE = pathlib.Path(__file__).parent

FIRST = ["Maya", "Jonas", "Priya", "Tomas", "Elena", "Kofi", "Lucia", "Arjun", "Hana", "Remy"]
LAST = ["Okafor", "Lindqvist", "Brandt", "Moreau", "Castillo", "Nakamura", "Haddad", "Whitfield"]
CATALOG = [
    ("USB-C cable", 12.99), ("Wireless mouse", 24.50), ("Desk lamp", 31.00),
    ("Notebook set", 14.25), ("Water bottle", 19.00), ("Phone stand", 16.75),
    ("Backpack", 54.00), ("Bluetooth speaker", 39.90), ("Ceramic mug", 11.50),
    ("Yoga mat", 28.00),
]

# (user_id, order_id, kind). `kind` decides the order's starting state.
ORDER_PLAN = [
    ("u1", "o1", "pending"),
    ("u1", "o2", "pending"),
    ("u2", "o3", "paid_cc"),
    ("u3", "o4", "paid_gc"),
    ("u3", "o5", "pending"),
    ("u4", "o6", "pending"),
    ("u5", "o7", "paid_cc"),
    ("u6", "o8", "paid_gc"),
]
# How each user's gift-card balance is set, relative to what their orders need.
#   "rich":  enough for every order the user owns, plus a margin
#   "poor":  less than the cheapest pending order they own
BALANCE_ROLE = {"u1": "rich", "u2": "rich", "u3": "rich", "u4": "poor", "u5": "rich", "u6": "poor"}


def build_world(seed=SEED):
    rng = random.Random(seed)
    names = [f"{f} {rng.choice(LAST)}" for f in rng.sample(FIRST, 6)]  # unique first names

    orders = {}
    for user_id, order_id, kind in ORDER_PLAN:
        items = [dict(name=n, price=p) for n, p in rng.sample(CATALOG, rng.randint(1, 2))]
        total = round(sum(i["price"] for i in items), 2)
        status, payments = "pending", []
        if kind == "paid_cc":
            status, payments = "paid", [{"method": "credit_card", "amount": total}]
        elif kind == "paid_gc":
            status, payments = "paid", [{"method": "gift_card", "amount": total}]
        orders[order_id] = {
            "order_id": order_id, "user_id": user_id, "items": items,
            "total": total, "status": status, "payments": payments,
        }

    users = {}
    for i, name in enumerate(names, start=1):
        uid = f"u{i}"
        mine = [o for o in orders.values() if o["user_id"] == uid]
        need = sum(o["total"] for o in mine)
        pending_totals = [o["total"] for o in mine if o["status"] == "pending"]
        if BALANCE_ROLE[uid] == "rich":
            balance = round(need + rng.randint(12, 45) + rng.choice([0, 0.5, 0.75]), 2)
        else:
            cap = min(pending_totals) if pending_totals else 30
            balance = round(rng.uniform(0.35, 0.6) * cap, 2)
        users[uid] = {
            "user_id": uid, "name": name, "gift_card_balance": balance,
            "order_ids": [o["order_id"] for o in mine],
        }
    return users, orders


def main():
    users, orders = build_world()
    (HERE / "users.json").write_text(json.dumps(list(users.values()), indent=2) + "\n")
    (HERE / "orders.json").write_text(json.dumps(list(orders.values()), indent=2) + "\n")
    for u in users.values():
        print(u["user_id"], u["name"], f"${u['gift_card_balance']:.2f}", u["order_ids"])
    for o in orders.values():
        print(o["order_id"], o["user_id"], f"${o['total']:.2f}", o["status"], o["payments"])


if __name__ == "__main__":
    main()
