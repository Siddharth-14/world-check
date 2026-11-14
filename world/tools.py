"""Three simulated retail tools over the seeded world.

    get_user(user_id)
    pay_with_gift_card(user_id, order_id, amount)
    modify_order_payment(order_id, new_method)

The persisted store is the only source of truth. Each tool computes its change
and then writes records back. Fault flags on `Env` plant the failures this demo
is about:

    persist_user=False   the user record is changed but never written back
                         (the tool still reports success and the new balance)
    stale                get_user serves an old snapshot for the next N calls
    timeout_once         the first write call "times out" after partly or fully
                         applying: "after_full_apply" or "after_user_write"
    guard_duplicates     when False, a repeated payment is not rejected

`change_log` records what each tool says it changed. `write_set` records which
records actually reached the store. Graders read both.
"""
import copy

METHODS = ("gift_card", "credit_card")


def r2(x):
    return round(x + 0.0, 2)


class Env:
    def __init__(self, users, orders, persist_user=True, stale=None,
                 timeout_once=None, guard_duplicates=True):
        self.initial = {"users": copy.deepcopy(users), "orders": copy.deepcopy(orders)}
        self.store = copy.deepcopy(self.initial)
        self.persist_user = persist_user
        self.stale = copy.deepcopy(stale or {})  # {user_id: {"record": {...}, "serves": n}}
        self.timeout_once = timeout_once
        self.guard_duplicates = guard_duplicates
        self._timed_out = False
        self.change_log = []   # what tools claim to have changed
        self.write_set = []    # record keys that were actually persisted

    # ---- persistence layer -------------------------------------------------
    def _commit_user(self, tool, user, new_balance):
        old = user["gift_card_balance"]
        self.change_log.append({"tool": tool, "record": f"user:{user['user_id']}",
                                "field": "gift_card_balance", "old": old, "new": new_balance})
        if self.persist_user:
            self.store["users"][user["user_id"]]["gift_card_balance"] = new_balance
            self.write_set.append(f"user:{user['user_id']}")
        # else: dropped write. Nothing is stored, nothing is reported.

    def _commit_order(self, tool, order_id, new_order):
        old = self.store["orders"][order_id]
        self.change_log.append({"tool": tool, "record": f"order:{order_id}",
                                "field": "payments/status",
                                "old": {"status": old["status"], "payments": old["payments"]},
                                "new": {"status": new_order["status"], "payments": new_order["payments"]}})
        self.store["orders"][order_id] = new_order
        self.write_set.append(f"order:{order_id}")

    def _maybe_timeout(self, point):
        if self.timeout_once == point and not self._timed_out:
            self._timed_out = True
            return {"ok": False, "error": "TimeoutError: upstream payment service did not respond within 30s"}
        return None

    # ---- tools -------------------------------------------------------------
    def get_user(self, user_id):
        user = self.store["users"].get(user_id)
        if user is None:
            return {"ok": False, "error": f"user {user_id} not found"}
        s = self.stale.get(user_id)
        if s and s["serves"] > 0:
            s["serves"] -= 1
            rec = s["record"]
        else:
            rec = user
        orders = [{"order_id": oid, "total": self.store["orders"][oid]["total"],
                   "status": self.store["orders"][oid]["status"]} for oid in user["order_ids"]]
        return {"ok": True, "user_id": rec["user_id"], "name": rec["name"],
                "gift_card_balance": rec["gift_card_balance"], "orders": orders}

    def pay_with_gift_card(self, user_id, order_id, amount):
        tool = "pay_with_gift_card"
        user = self.store["users"].get(user_id)
        order = self.store["orders"].get(order_id)
        if user is None or order is None or order["user_id"] != user_id:
            return {"ok": False, "error": "user/order mismatch or not found"}
        amount = r2(amount)
        due = r2(order["total"] - sum(p["amount"] for p in order["payments"]))
        if self.guard_duplicates:
            if order["status"] != "pending":
                return {"ok": False, "error": f"order {order_id} is not pending (status: {order['status']})"}
            if amount > due + 0.001:
                return {"ok": False, "error": f"amount {amount:.2f} exceeds amount due {due:.2f}"}
        if amount <= 0:
            return {"ok": False, "error": "amount must be positive"}
        if user["gift_card_balance"] + 0.001 < amount:
            return {"ok": False, "error": f"insufficient gift card balance ({user['gift_card_balance']:.2f} < {amount:.2f})"}

        new_balance = r2(user["gift_card_balance"] - amount)
        self._commit_user(tool, user, new_balance)
        t = self._maybe_timeout("after_user_write")
        if t:
            return t

        new_order = copy.deepcopy(order)
        new_order["payments"].append({"method": "gift_card", "amount": amount})
        paid = r2(sum(p["amount"] for p in new_order["payments"]))
        new_order["status"] = "paid" if paid + 0.001 >= order["total"] else "pending"
        self._commit_order(tool, order_id, new_order)
        t = self._maybe_timeout("after_full_apply")
        if t:
            return t
        return {"ok": True, "order_id": order_id, "paid": amount, "order_status": new_order["status"],
                "new_gift_card_balance": new_balance}

    def modify_order_payment(self, order_id, new_method):
        """Re-pay the whole order with `new_method`. Existing gift-card payments are refunded
        to the user's balance first. Credit-card refunds/charges are not modelled."""
        tool = "modify_order_payment"
        if new_method not in METHODS:
            return {"ok": False, "error": f"unknown method {new_method}"}
        order = self.store["orders"].get(order_id)
        if order is None:
            return {"ok": False, "error": f"order {order_id} not found"}
        user = self.store["users"][order["user_id"]]
        methods = {p["method"] for p in order["payments"]}
        if order["status"] == "paid" and methods == {new_method}:
            return {"ok": False, "error": f"order {order_id} is already paid with {new_method}"}

        refund = r2(sum(p["amount"] for p in order["payments"] if p["method"] == "gift_card"))
        balance = r2(user["gift_card_balance"] + refund)
        charge = order["total"] if new_method == "gift_card" else 0.0
        if balance + 0.001 < charge:
            return {"ok": False, "error": f"insufficient gift card balance ({balance:.2f} < {charge:.2f})"}
        new_balance = r2(balance - charge)
        if new_balance != user["gift_card_balance"]:
            self._commit_user(tool, user, new_balance)
        t = self._maybe_timeout("after_user_write")
        if t:
            return t

        new_order = copy.deepcopy(order)
        new_order["payments"] = [{"method": new_method, "amount": order["total"]}]
        new_order["status"] = "paid"
        self._commit_order(tool, order_id, new_order)
        t = self._maybe_timeout("after_full_apply")
        if t:
            return t
        return {"ok": True, "order_id": order_id, "payment_method": new_method, "order_status": "paid",
                "refunded_to_gift_card": refund, "new_gift_card_balance": new_balance}

    def call(self, name, **args):
        return getattr(self, name)(**args)
