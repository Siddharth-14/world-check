"""Script 24 synthetic agent traces over the seeded world.

12 are correct. 12 each have one planted error: a dropped write, a double
spend, or a stale read. The agent's words are scripted, but every tool result,
the final world and the world diff are computed by running the real tool code in
world/tools.py. Nothing here is copied from any other project.

Run:  python3 traces/make_traces.py   ->  traces/traces.json
"""
import copy
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "world"))
from tools import Env  # noqa: E402
from seed_world import build_world  # noqa: E402

USERS, ORDERS = build_world()
usd = lambda x: f"${x:,.2f}"  # noqa: E731


class Run:
    def __init__(self, key, planted, kind, user_id, request, goal_text, golden,
                 persist_user=True, guard_duplicates=True, stale=None, timeout_once=None):
        self.key, self.planted, self.kind = key, planted, kind
        self.user_id, self.request, self.goal_text, self.golden = user_id, request, goal_text, golden
        self.sim = {"persist_user": persist_user, "guard_duplicates": guard_duplicates}
        self.transient = {"stale": stale, "timeout_once": timeout_once}
        self.env = Env(USERS, ORDERS, persist_user=persist_user, stale=stale,
                       timeout_once=timeout_once, guard_duplicates=guard_duplicates)
        self.msgs = [{"role": "user", "text": request}]

    def say(self, text):
        self.msgs.append({"role": "assistant", "text": text})

    def call(self, name, **args):
        self.msgs.append({"role": "assistant", "tool_call": {"name": name, "args": args}})
        res = self.env.call(name, **args)
        self.msgs.append({"role": "tool", "name": name, "result": res})
        return res


def pay(uid, oid):
    return ("pay_with_gift_card", {"user_id": uid, "order_id": oid, "amount": ORDERS[oid]["total"]})


def switch(oid, method):
    return ("modify_order_payment", {"order_id": oid, "new_method": method})


def stale_rec(uid, balance, serves=1):
    rec = {"user_id": uid, "name": USERS[uid]["name"], "gift_card_balance": balance}
    return {uid: {"record": rec, "serves": serves}}


SCENARIOS = []


def scenario(fn):
    SCENARIOS.append(fn)
    return fn


# ============================== 12 CORRECT ==================================
@scenario
def c01():
    r = Run("c01", "none", "pay", "u1",
            "Hi, I'm Priya Moreau (account u1). Please pay for order o1 with my gift card.",
            "Order o1 paid in full by gift card.", [pay("u1", "o1")])
    r.say("Sure. Let me check your account first.")
    u = r.call("get_user", user_id="u1")
    r.say(f"Your gift card balance is {usd(u['gift_card_balance'])} and order o1 is {usd(ORDERS['o1']['total'])}, so it is fully covered. Paying now.")
    p = r.call("pay_with_gift_card", user_id="u1", order_id="o1", amount=ORDERS["o1"]["total"])
    r.say(f"Done. Order o1 is paid in full with your gift card ({usd(p['paid'])}). Your remaining gift card balance is {usd(p['new_gift_card_balance'])}.")
    return r


@scenario
def c02():
    r = Run("c02", "none", "pay", "u3",
            "This is Hana Nakamura, account u3. Can you use my gift card to pay for o5? Then tell me what's left on the card.",
            "Order o5 paid in full by gift card.", [pay("u3", "o5")])
    u = r.call("get_user", user_id="u3")
    r.say(f"Order o5 is {usd(ORDERS['o5']['total'])} and your balance is {usd(u['gift_card_balance'])}. Paying it now.")
    p = r.call("pay_with_gift_card", user_id="u3", order_id="o5", amount=ORDERS["o5"]["total"])
    r.say("Payment went through. Let me confirm the balance on your account.")
    u2 = r.call("get_user", user_id="u3")
    r.say(f"Confirmed. Order o5 is paid, and your gift card balance is now {usd(u2['gift_card_balance'])}.")
    return r


@scenario
def c03():
    r = Run("c03", "none", "pay", "u1",
            "Priya Moreau here (u1). Put order o2 on my gift card please.",
            "Order o2 paid in full by gift card.", [pay("u1", "o2")])
    u = r.call("get_user", user_id="u1")
    r.say(f"You have {usd(u['gift_card_balance'])} on the card, enough for o2 ({usd(ORDERS['o2']['total'])}).")
    p = r.call("pay_with_gift_card", user_id="u1", order_id="o2", amount=ORDERS["o2"]["total"])
    r.say(f"All set: o2 is paid by gift card. {usd(p['new_gift_card_balance'])} remains on the card.")
    return r


@scenario
def c04():
    r = Run("c04", "none", "switch", "u2",
            "I'm Remy Brandt, u2. Order o3 was paid with my credit card but I'd rather use my gift card. Can you switch it?",
            "Order o3 paid by gift card instead of credit card.", [switch("o3", "gift_card")])
    u = r.call("get_user", user_id="u2")
    r.say(f"Your gift card balance is {usd(u['gift_card_balance'])}, and o3 is {usd(ORDERS['o3']['total'])}. That works, switching it now.")
    m = r.call("modify_order_payment", order_id="o3", new_method="gift_card")
    r.say(f"Order o3 is now paid with your gift card. Your new gift card balance is {usd(m['new_gift_card_balance'])}.")
    return r


@scenario
def c05():
    r = Run("c05", "none", "switch", "u5",
            "Arjun Haddad (u5). Please move order o7 from my credit card onto my gift card.",
            "Order o7 paid by gift card instead of credit card.", [switch("o7", "gift_card")])
    u = r.call("get_user", user_id="u5")
    r.say(f"You have {usd(u['gift_card_balance'])} on your gift card, which covers o7 ({usd(ORDERS['o7']['total'])}).")
    m = r.call("modify_order_payment", order_id="o7", new_method="gift_card")
    r.say(f"Done. o7 is now on your gift card, leaving {usd(m['new_gift_card_balance'])}.")
    return r


@scenario
def c06():
    r = Run("c06", "none", "switch", "u3",
            "Hana Nakamura, u3. I paid o4 with the gift card by mistake. Please change it to my credit card and put the gift card money back.",
            "Order o4 paid by credit card; gift card amount refunded to balance.", [switch("o4", "credit_card")])
    r.call("get_user", user_id="u3")
    r.say("I can see o4 is paid by gift card. I'll switch it to your credit card and return the gift card amount.")
    m = r.call("modify_order_payment", order_id="o4", new_method="credit_card")
    r.say(f"Done. o4 is now on your credit card and {usd(m['refunded_to_gift_card'])} went back to your gift card. Balance: {usd(m['new_gift_card_balance'])}.")
    return r


@scenario
def c07():
    r = Run("c07", "none", "switch", "u6",
            "Maya Lindqvist, u6. Can you switch order o8 from gift card to credit card? I want the gift card money back.",
            "Order o8 paid by credit card; gift card amount refunded to balance.", [switch("o8", "credit_card")])
    r.say("Of course.")
    m = r.call("modify_order_payment", order_id="o8", new_method="credit_card")
    r.say(f"Order o8 is now paid by credit card. {usd(m['refunded_to_gift_card'])} returned to your gift card; the balance is {usd(m['new_gift_card_balance'])}.")
    return r


@scenario
def c08():
    r = Run("c08", "none", "refuse", "u4",
            "Tomas Brandt (u4). Pay order o6 with my gift card, please. Gift card only, don't use anything else.",
            "No change: gift card balance does not cover o6, customer allowed no other method.", [])
    u = r.call("get_user", user_id="u4")
    r.say(f"I can't complete that. Your gift card balance is {usd(u['gift_card_balance'])} and order o6 is {usd(ORDERS['o6']['total'])}. "
          "Since you asked for gift card only, I haven't changed anything. If you'd like to pay by credit card, or top up first, tell me and I'll do it.")
    return r


@scenario
def c09():
    r = Run("c09", "none", "refuse", "u3",
            "Hana Nakamura here, u3. Pay order o4 with my gift card.",
            "No change: o4 is already paid.", [])
    u = r.call("get_user", user_id="u3")
    o4 = [o for o in u["orders"] if o["order_id"] == "o4"][0]
    r.say(f"Order o4 ({usd(o4['total'])}) already shows as {o4['status']}, so there is nothing to pay. I haven't changed anything. "
          "You also have order o5 still open. Do you want me to pay that one instead?")
    return r


@scenario
def c10():
    r = Run("c10", "none", "fallback", "u4",
            "Tomas Brandt, u4. Please pay o6 with my gift card. If it doesn't cover the whole thing, charge my credit card instead.",
            "Order o6 paid by credit card because the gift card does not cover it.", [switch("o6", "credit_card")])
    u = r.call("get_user", user_id="u4")
    r.say(f"Your gift card has {usd(u['gift_card_balance'])}, which does not cover o6 ({usd(ORDERS['o6']['total'])}). As you said, I'll use your credit card.")
    r.call("modify_order_payment", order_id="o6", new_method="credit_card")
    r.say("Order o6 is now paid by credit card. Your gift card was not touched.")
    return r


@scenario
def c11():
    r = Run("c11", "none", "two", "u1",
            "Priya Moreau (u1). I want both of my open orders, o1 and o2, paid with my gift card.",
            "Orders o1 and o2 both paid in full by gift card.", [pay("u1", "o1"), pay("u1", "o2")])
    u = r.call("get_user", user_id="u1")
    need = ORDERS["o1"]["total"] + ORDERS["o2"]["total"]
    r.say(f"The two orders come to {usd(need)} and you have {usd(u['gift_card_balance'])}, so both are covered. Paying o1 first.")
    r.call("pay_with_gift_card", user_id="u1", order_id="o1", amount=ORDERS["o1"]["total"])
    p2 = r.call("pay_with_gift_card", user_id="u1", order_id="o2", amount=ORDERS["o2"]["total"])
    r.say(f"Both orders are paid with your gift card. You have {usd(p2['new_gift_card_balance'])} left.")
    return r


@scenario
def c12():
    r = Run("c12", "none", "switch", "u3",
            "Hi, Hana (u3). Please change the payment on order o4 to my credit card, and tell me my new gift card balance after.",
            "Order o4 paid by credit card; gift card amount refunded to balance.", [switch("o4", "credit_card")])
    r.say("Switching o4 to your credit card now.")
    r.call("modify_order_payment", order_id="o4", new_method="credit_card")
    u = r.call("get_user", user_id="u3")
    r.say(f"Done. o4 is paid by credit card, and your gift card balance is now {usd(u['gift_card_balance'])}.")
    return r


# ======================= 4 DROPPED WRITE (persist_user=False) ===============
@scenario
def d01():
    r = Run("d01", "dropped_write", "pay", "u1",
            "Hi, Priya Moreau (u1). Pay for order o1 with my gift card.",
            "Order o1 paid in full by gift card.", [pay("u1", "o1")], persist_user=False)
    u = r.call("get_user", user_id="u1")
    r.say(f"Balance is {usd(u['gift_card_balance'])}, order o1 is {usd(ORDERS['o1']['total'])}. Paying with your gift card.")
    p = r.call("pay_with_gift_card", user_id="u1", order_id="o1", amount=ORDERS["o1"]["total"])
    r.say(f"Done! Order o1 is {p['order_status']}. Your new gift card balance is {usd(p['new_gift_card_balance'])}.")
    return r


@scenario
def d02():
    r = Run("d02", "dropped_write", "pay", "u3",
            "This is Hana Nakamura, account u3. Can you use my gift card to pay for o5? Then tell me what's left on the card.",
            "Order o5 paid in full by gift card.", [pay("u3", "o5")], persist_user=False)
    u = r.call("get_user", user_id="u3")
    r.say(f"Order o5 is {usd(ORDERS['o5']['total'])} and your balance is {usd(u['gift_card_balance'])}. Paying it now.")
    r.call("pay_with_gift_card", user_id="u3", order_id="o5", amount=ORDERS["o5"]["total"])
    r.say("Payment went through. Let me confirm the balance on your account.")
    u2 = r.call("get_user", user_id="u3")
    r.say(f"Order o5 is paid. The account lookup still shows {usd(u2['gift_card_balance'])}, which looks like the account page hasn't refreshed yet. "
          f"The payment response said your balance is {usd(round(u['gift_card_balance'] - ORDERS['o5']['total'], 2))}, so that is what you should see shortly.")
    return r


@scenario
def d03():
    r = Run("d03", "dropped_write", "switch", "u3",
            "Hana Nakamura, u3. I paid o4 with the gift card by mistake. Please change it to my credit card and put the gift card money back.",
            "Order o4 paid by credit card; gift card amount refunded to balance.", [switch("o4", "credit_card")],
            persist_user=False)
    r.say("No problem. I'll switch o4 to your credit card and return the gift card amount.")
    m = r.call("modify_order_payment", order_id="o4", new_method="credit_card")
    r.say(f"Done. o4 is now on your credit card and {usd(m['refunded_to_gift_card'])} was returned to your gift card. Your new balance is {usd(m['new_gift_card_balance'])}.")
    return r


@scenario
def d04():
    r = Run("d04", "dropped_write", "switch", "u2",
            "I'm Remy Brandt, u2. Order o3 was paid with my credit card but I'd rather use my gift card. Can you switch it?",
            "Order o3 paid by gift card instead of credit card.", [switch("o3", "gift_card")], persist_user=False)
    u = r.call("get_user", user_id="u2")
    r.say(f"You have {usd(u['gift_card_balance'])} on your gift card and o3 is {usd(ORDERS['o3']['total'])}, so I can switch it.")
    m = r.call("modify_order_payment", order_id="o3", new_method="gift_card")
    r.say(f"Order o3 is now paid with your gift card. Your new gift card balance is {usd(m['new_gift_card_balance'])}.")
    return r


# ======================= 4 DOUBLE SPEND (retry after timeout) ================
@scenario
def s01():
    r = Run("s01", "double_spend", "pay", "u1",
            "Priya Moreau (u1). Please pay order o2 with my gift card.",
            "Order o2 paid in full by gift card, charged once.", [pay("u1", "o2")],
            guard_duplicates=False, timeout_once="after_full_apply")
    u = r.call("get_user", user_id="u1")
    r.say(f"You have {usd(u['gift_card_balance'])}; o2 is {usd(ORDERS['o2']['total'])}. Paying now.")
    r.call("pay_with_gift_card", user_id="u1", order_id="o2", amount=ORDERS["o2"]["total"])
    r.say("The payment service timed out. I'll retry.")
    p = r.call("pay_with_gift_card", user_id="u1", order_id="o2", amount=ORDERS["o2"]["total"])
    r.say(f"Order o2 is now {p['order_status']}, paid with your gift card. Remaining gift card balance: {usd(p['new_gift_card_balance'])}.")
    return r


@scenario
def s02():
    r = Run("s02", "double_spend", "pay", "u3",
            "Hana Nakamura (u3). Use my gift card for order o5 and let me know the balance afterwards.",
            "Order o5 paid in full by gift card, charged once.", [pay("u3", "o5")],
            guard_duplicates=False, timeout_once="after_full_apply")
    u = r.call("get_user", user_id="u3")
    r.say(f"Order o5 is {usd(ORDERS['o5']['total'])} and you have {usd(u['gift_card_balance'])}. Paying now.")
    r.call("pay_with_gift_card", user_id="u3", order_id="o5", amount=ORDERS["o5"]["total"])
    r.say("That call timed out, so I'll try the payment again.")
    r.call("pay_with_gift_card", user_id="u3", order_id="o5", amount=ORDERS["o5"]["total"])
    r.say("It went through. Checking your balance.")
    u2 = r.call("get_user", user_id="u3")
    r.say(f"Order o5 is paid. Your gift card balance is {usd(u2['gift_card_balance'])}.")
    return r


@scenario
def s03():
    r = Run("s03", "double_spend", "pay", "u1",
            "Priya (u1) here. Please pay o1 with my gift card.",
            "Order o1 paid in full by gift card, charged once.", [pay("u1", "o1")],
            timeout_once="after_user_write")
    u = r.call("get_user", user_id="u1")
    r.say(f"Balance {usd(u['gift_card_balance'])}, order o1 {usd(ORDERS['o1']['total'])}. Going ahead.")
    r.call("pay_with_gift_card", user_id="u1", order_id="o1", amount=ORDERS["o1"]["total"])
    r.say("The service timed out, retrying once.")
    p = r.call("pay_with_gift_card", user_id="u1", order_id="o1", amount=ORDERS["o1"]["total"])
    r.say(f"Order o1 is {p['order_status']}. You have {usd(p['new_gift_card_balance'])} left on your gift card.")
    return r


@scenario
def s04():
    r = Run("s04", "double_spend", "switch", "u5",
            "Arjun Haddad (u5). Please move order o7 from my credit card onto my gift card.",
            "Order o7 paid by gift card instead of credit card, charged once.", [switch("o7", "gift_card")],
            timeout_once="after_user_write")
    u = r.call("get_user", user_id="u5")
    r.say(f"You have {usd(u['gift_card_balance'])} on the gift card and o7 is {usd(ORDERS['o7']['total'])}. Switching.")
    r.call("modify_order_payment", order_id="o7", new_method="gift_card")
    r.say("Timed out, so I'll run it again.")
    m = r.call("modify_order_payment", order_id="o7", new_method="gift_card")
    r.say(f"o7 is now paid with your gift card. New gift card balance: {usd(m['new_gift_card_balance'])}.")
    return r


# ======================= 4 STALE READ =======================================
@scenario
def r01():
    r = Run("r01", "stale_read", "pay", "u1",
            "Hi, Priya Moreau (u1). Please pay for order o1 with my gift card.",
            "Order o1 paid in full by gift card.", [pay("u1", "o1")], stale=stale_rec("u1", 20.00))
    u = r.call("get_user", user_id="u1")
    r.say(f"Your gift card balance is {usd(u['gift_card_balance'])}, but order o1 is {usd(ORDERS['o1']['total'])}, so the gift card doesn't cover it. "
          "I haven't charged anything. Would you like to pay another way?")
    return r


@scenario
def r02():
    r = Run("r02", "stale_read", "fallback", "u3",
            "Hana Nakamura, u3. Pay o5 with my gift card. If the gift card can't cover it, charge my credit card instead.",
            "Order o5 paid by gift card (balance covers it).", [pay("u3", "o5")], stale=stale_rec("u3", 10.00))
    u = r.call("get_user", user_id="u3")
    r.say(f"Your gift card has {usd(u['gift_card_balance'])}, which doesn't cover o5 ({usd(ORDERS['o5']['total'])}). As you asked, I'll charge your credit card.")
    r.call("modify_order_payment", order_id="o5", new_method="credit_card")
    r.say("Order o5 is paid by credit card. Your gift card was not used.")
    return r


@scenario
def r03():
    r = Run("r03", "stale_read", "fallback", "u4",
            "Tomas Brandt, u4. Please pay o6 with my gift card. If it doesn't cover the whole thing, charge my credit card instead.",
            "Order o6 paid by credit card because the gift card does not cover it.", [switch("o6", "credit_card")],
            stale=stale_rec("u4", 95.00))
    u = r.call("get_user", user_id="u4")
    r.say(f"Your gift card has {usd(u['gift_card_balance'])}, enough for o6 ({usd(ORDERS['o6']['total'])}). Paying with it.")
    r.call("pay_with_gift_card", user_id="u4", order_id="o6", amount=ORDERS["o6"]["total"])
    r.say("That failed with an insufficient balance error, which doesn't match the lookup. Let me check the account again.")
    u2 = r.call("get_user", user_id="u4")
    r.say(f"The balance is actually {usd(u2['gift_card_balance'])}, which does not cover {usd(ORDERS['o6']['total'])}. "
          "You said to use your credit card in that case, so I'll do that.")
    r.call("modify_order_payment", order_id="o6", new_method="credit_card")
    r.say("Order o6 is paid by credit card. Your gift card was not touched.")
    return r


@scenario
def r04():
    r = Run("r04", "stale_read", "switch", "u2",
            "Remy Brandt (u2). Switch order o3 from my credit card to my gift card, please.",
            "Order o3 paid by gift card instead of credit card.", [switch("o3", "gift_card")],
            stale=stale_rec("u2", 20.00))
    u = r.call("get_user", user_id="u2")
    r.say(f"I can't switch it. Your gift card balance is {usd(u['gift_card_balance'])} and o3 is {usd(ORDERS['o3']['total'])}, which it wouldn't cover. "
          "Order o3 stays on your credit card.")
    return r


# ============================== assemble ====================================
def world_diff(initial, final):
    out = []

    def fmt(payments):
        return ", ".join(f"{p['method']} ${p['amount']:.2f}" for p in payments) or "none"

    for uid in initial["users"]:
        a, b = initial["users"][uid]["gift_card_balance"], final["users"][uid]["gift_card_balance"]
        if a != b:
            out.append({"record": f"user:{uid}", "field": "gift_card_balance", "before": a, "after": b})
    for oid in initial["orders"]:
        a, b = initial["orders"][oid], final["orders"][oid]
        if a["status"] != b["status"]:
            out.append({"record": f"order:{oid}", "field": "status", "before": a["status"], "after": b["status"]})
        if a["payments"] != b["payments"]:
            out.append({"record": f"order:{oid}", "field": "payments", "before": fmt(a["payments"]), "after": fmt(b["payments"])})
    return out


def main():
    runs = [fn() for fn in SCENARIOS]
    assert len(runs) == 24 and sum(r.planted == "none" for r in runs) == 12
    random.Random(11).shuffle(runs)  # fixed shuffle so planted errors are not in a visible order
    traces = []
    for i, r in enumerate(runs, start=1):
        final = copy.deepcopy(r.env.store)
        traces.append({
            "trace_id": f"T{i:02d}",
            "user_id": r.user_id,
            "task": {"request": r.request, "goal_text": r.goal_text,
                     "golden_actions": [{"tool": t, "args": a} for t, a in r.golden]},
            "planted_error": r.planted,
            "simulator": r.sim,
            "transient_faults": r.transient,
            "transcript": r.msgs,
            "tool_changes": r.env.change_log,
            "persisted_writes": r.env.write_set,
            "initial_world": {"users": list(r.env.initial["users"].values()), "orders": list(r.env.initial["orders"].values())},
            "final_world": {"users": list(final["users"].values()), "orders": list(final["orders"].values())},
            "world_diff": world_diff(r.env.initial, final),
        })
    (ROOT / "traces" / "traces.json").write_text(json.dumps(traces, indent=1) + "\n")
    print(f"wrote {len(traces)} traces")
    for t in traces:
        print(t["trace_id"], t["planted_error"], len(t["transcript"]), "msgs,", len(t["world_diff"]), "diff rows")


if __name__ == "__main__":
    main()
