"""Smoke tests for the Knowledge Retrieval API (stdlib only).

Run against a live server:  python tests/test_api.py [base_url]
"""
import json
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


status, body = call("GET", "/")
check("GET / running", status == 200 and body.get("status") == "running", body)

status, body = call("GET", "/health")
check("GET /health reports 18 articles", status == 200 and body.get("knowledge_base_articles") == 18, body)

# Known-good retrievals (README sample queries)
cases = [
    ("incident", "IT", "My VPN keeps disconnecting repeatedly.", "INC001"),
    ("incident", "non-IT", "The office air conditioning is not working.", "INC006"),
    ("change", "IT", "I need new software installed.", "CHG001"),
    ("change", "non-IT", "I need to change the office seating layout.", "CHG004"),
    ("problem", "IT", "The VPN keeps disconnecting repeatedly for several employees.", "PRB001"),
    ("problem", "non-IT", "The office air conditioning keeps failing repeatedly.", "PRB004"),
]
for category, domain, text, expected in cases:
    status, body = call("POST", "/retrieve", {"category": category, "domain": domain, "request": text})
    kr = body.get("knowledge_retrieval", {})
    ids = kr.get("matched_article_ids", [])
    check(f"retrieve {category}/{domain} -> {expected}", status == 200 and bool(ids) and ids[0] == expected, (status, ids))
    check(f"  no escalation for {expected}", kr.get("escalation_required") is False)

# Strict routing: results never cross category/domain
status, body = call("POST", "/retrieve", {"category": "change", "domain": "IT", "request": "Please upgrade the production Postgres cluster"})
results = body.get("knowledge_retrieval", {}).get("results", [])
check("routing stays inside change/it", status == 200 and all(r["category"] == "change" and r["domain"] == "it" for r in results), results)

# Unrelated query must escalate rather than force a match
status, body = call("POST", "/retrieve", {"category": "incident", "domain": "IT", "request": "zzzz qqqq xxxx"})
kr = body.get("knowledge_retrieval", {})
check("gibberish escalates", status == 200 and kr.get("escalation_required") is True and kr.get("matched_article_ids") == [], body)

# Validation
for name, payload in [
    ("bad category -> 422", {"category": "bogus", "domain": "IT", "request": "x"}),
    ("bad domain -> 422", {"category": "incident", "domain": "bogus", "request": "x"}),
    ("empty request -> 422", {"category": "incident", "domain": "IT", "request": ""}),
    ("missing field -> 422", {"category": "incident"}),
    ("confidence>1 -> 422", {"category": "incident", "domain": "IT", "request": "x", "confidence": 2}),
]:
    status, _ = call("POST", "/retrieve", payload)
    check(name, status == 422, status)

# Domain spelling variants accepted
for variant in ("it", "IT", "non-it", "non-IT"):
    cat = "incident"
    status, _ = call("POST", "/retrieve", {"category": cat, "domain": variant, "request": "VPN drops"})
    check(f"domain variant {variant!r} accepted", status == 200, status)

print(f"\n{len(failures)} failure(s)" if failures else "\nAll API checks passed")
sys.exit(1 if failures else 0)
