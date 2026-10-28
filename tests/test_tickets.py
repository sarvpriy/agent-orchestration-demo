"""Ticket management tests (stdlib only), run against a live server with a throwaway DB.

Run:  python tests/test_tickets.py [base_url]
"""
import json
import re
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
failures = []


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {name}" + (f"  -> {detail}" if not condition else ""))
    if not condition:
        failures.append(name)


def ticket_input(request, title, description, category="incident", domain="IT", priority="P3"):
    return {"category": category, "domain": domain, "title": title,
            "description": description, "request": request, "priority": priority,
            "payload": {"severity": priority}}


# --- find-or-create: new incident creates a ticket
vpn = ticket_input("My VPN keeps disconnecting every few minutes",
                   "VPN keeps disconnecting", "User VPN drops every few minutes")
status, first = call("POST", "/tickets/find-or-create", vpn)
number = first.get("ticket", {}).get("number", "")
check("new incident -> 201 created", status == 201 and first.get("created") is True, (status, first))
check("number format INC0000001", re.fullmatch(r"INC\d{7}", number) is not None, number)
check("new ticket is open, occurrences=1",
      first["ticket"]["status"] == "open" and first["ticket"]["occurrences"] == 1, first.get("ticket"))

# --- same incident again -> no new ticket
status, second = call("POST", "/tickets/find-or-create", vpn)
check("same incident -> 200, not created", status == 200 and second.get("created") is False, (status, second))
check("duplicate points at first ticket", second.get("duplicate_of") == number, second.get("duplicate_of"))
check("occurrences incremented", second["ticket"]["occurrences"] == 2, second["ticket"])

# --- different incident, same category/domain -> new ticket
status, other = call("POST", "/tickets/find-or-create",
                     ticket_input("My laptop is running very slowly", "Laptop running slowly",
                                  "Laptop is extremely slow and freezes"))
check("different incident -> new ticket",
      status == 201 and other["created"] and other["ticket"]["number"] != number, (status, other))

# --- same wording, different category -> separate ticket with its own prefix
status, chg = call("POST", "/tickets/find-or-create",
                   ticket_input("My VPN keeps disconnecting every few minutes",
                                "VPN keeps disconnecting", "User VPN drops every few minutes",
                                category="change"))
check("other category -> new CHG ticket",
      status == 201 and chg["ticket"]["number"].startswith("CHG"), (status, chg))

# --- same wording, different domain -> separate ticket
status, dom = call("POST", "/tickets/find-or-create",
                   ticket_input("My VPN keeps disconnecting every few minutes",
                                "VPN keeps disconnecting", "User VPN drops every few minutes",
                                domain="non-IT"))
check("other domain -> new ticket", status == 201 and dom["created"], (status, dom))

# --- read / list
status, got = call("GET", f"/tickets/{number}")
kinds = [e["kind"] for e in got.get("events", [])]
check("GET ticket with history", status == 200 and kinds == ["created", "duplicate_report"], (status, kinds))
status, got_lower = call("GET", f"/tickets/{number.lower()}")
check("ticket lookup is case-insensitive", status == 200, status)
status, _ = call("GET", "/tickets/INC9999999")
check("unknown ticket -> 404", status == 404, status)
status, listing = call("GET", "/tickets?category=incident&domain=IT&status=open")
check("list filters", status == 200 and len(listing) == 2
      and all(t["category"] == "incident" and t["domain"] == "it" for t in listing), listing)
status, _ = call("GET", "/tickets?status=bogus")
check("list bad status -> 422", status == 422, status)

# --- lifecycle
status, upd = call("PATCH", f"/tickets/{number}", {"status": "in_progress", "assignee": "alice"})
check("open -> in_progress + assignee",
      status == 200 and upd["status"] == "in_progress" and upd["assignee"] == "alice", (status, upd))
status, _ = call("PATCH", f"/tickets/{number}", {"status": "resolved"})
check("resolve without resolution -> 422", status == 422, status)
status, upd = call("PATCH", f"/tickets/{number}", {"status": "resolved", "resolution": "Reinstalled VPN client", "comment": "fixed"})
check("resolve with resolution", status == 200 and upd["status"] == "resolved", (status, upd))
status, _ = call("PATCH", f"/tickets/{number}", {"status": "in_progress"})
check("resolved -> in_progress rejected", status == 422, status)
status, _ = call("PATCH", "/tickets/INC9999999", {"status": "closed"})
check("patch unknown -> 404", status == 404, status)

# --- resolved tickets are not reused: the same incident opens a fresh ticket
status, again = call("POST", "/tickets/find-or-create", vpn)
check("after resolve, same incident -> new ticket",
      status == 201 and again["created"] and again["ticket"]["number"] != number, (status, again))

status, closed = call("PATCH", f"/tickets/{number}", {"status": "closed"})
check("resolved -> closed", status == 200 and closed["status"] == "closed", (status, closed))
status, _ = call("PATCH", f"/tickets/{number}", {"status": "open"})
check("closed is final", status == 422, status)

# --- validation
for name, payload in [
    ("bad category -> 422", {**vpn, "category": "bogus"}),
    ("bad domain -> 422", {**vpn, "domain": "bogus"}),
    ("empty title -> 422", {**vpn, "title": ""}),
    ("missing description -> 422", {k: v for k, v in vpn.items() if k != "description"}),
]:
    status, _ = call("POST", "/tickets/find-or-create", payload)
    check(name, status == 422, status)

# --- forced create bypasses duplicate check
status, a = call("POST", "/tickets", ticket_input("x", "Printer jam", "Printer jams", domain="non-IT"))
status2, b = call("POST", "/tickets", ticket_input("x", "Printer jam", "Printer jams", domain="non-IT"))
check("POST /tickets always creates", status == 201 and status2 == 201 and a["number"] != b["number"], (status, status2))

print(f"\n{len(failures)} failure(s)" if failures else "\nAll ticket checks passed")
sys.exit(1 if failures else 0)
