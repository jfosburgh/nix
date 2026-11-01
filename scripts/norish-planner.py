#!/usr/bin/env python3
"""Agent-facing Norish macro planning. Standard library only; no LLM required."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

MACROS = ("calories", "fat", "carbs", "protein")
SLOTS = ("Breakfast", "Lunch", "Dinner", "Snack")
DEFAULT_URL = "https://recipes.threegoldenhairs.me"
FDC_BASE = "https://api.nal.usda.gov"
# Stable FoodData Central nutrient IDs for the four macros.
FDC_NUTRIENT_IDS = {"calories": 1008, "protein": 1003, "fat": 1004, "carbs": 1005}
MASS_UNITS = {"g": 1, "gram": 1, "grams": 1, "kg": 1000, "ounce": 28.3495, "pound": 453.619,
              "fl oz": 28.3495, "fluid ounce": 28.3495, "oz": 28.3495}
# "shot" is treated as 30 ml (one espresso shot); a double shot is therefore 60 ml.
VOLUME_UNITS = {"ml": 1, "milliliter": 1, "l": 1000, "cup": 240, "tbsp": 15, "tablespoon": 15,
                "tsp": 5, "teaspoon": 5, "shot": 30, "shots": 30}


class PlannerError(Exception):
    pass


def read_json(path):
    def invalid(value):
        raise PlannerError(f"Invalid JSON number: {value}")
    with open(path) as handle:
        return json.load(handle, parse_constant=invalid)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PlannerError(f"{label} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise PlannerError(f"{label} must be {'positive' if positive else 'nonnegative'}")
    return value


def stored_macro(value, label):
    # PostgreSQL decimal columns are serialized as strings by the live API.
    # Only recipe values get this coercion; plan targets remain strict numbers.
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            raise PlannerError(f"{label} must be a finite number or numeric string") from None
    return number(value, label)


def date(value):
    try:
        parsed = dt.date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (TypeError, ValueError):
        raise PlannerError(f"Invalid ISO date: {value!r}") from None


def recipe_id(value):
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError):
        raise PlannerError(f"Invalid recipe UUID: {value!r}") from None


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) - {"targets", "tolerance", "days"}:
        raise PlannerError("Plan must contain only targets, tolerance and days")
    targets = plan.get("targets")
    if not isinstance(targets, dict) or set(targets) != set(MACROS):
        raise PlannerError(f"targets must specify exactly {', '.join(MACROS)} (kcal and grams)")
    for macro in MACROS:
        number(targets[macro], f"targets.{macro}")
    if targets["calories"] <= 0:
        raise PlannerError("Calorie target must be positive")
    tolerance = number(plan.get("tolerance", 0.10), "tolerance")
    if tolerance > 1:
        raise PlannerError("tolerance must be between 0 and 1")
    days = plan.get("days")
    if not isinstance(days, list) or not days:
        raise PlannerError("days must be a nonempty list")
    seen_days = set()
    for day in days:
        if not isinstance(day, dict) or set(day) != {"date", "meals"}:
            raise PlannerError("Each day must have exactly date and meals")
        date(day["date"])
        if day["date"] in seen_days:
            raise PlannerError("Duplicate date; combine its meals into one day")
        seen_days.add(day["date"])
        if not isinstance(day["meals"], list) or not day["meals"]:
            raise PlannerError("Each day needs at least one meal")
        seen = set()
        for meal in day["meals"]:
            if not isinstance(meal, dict) or set(meal) != {"slot", "recipeId", "servings"}:
                raise PlannerError("Each meal must have exactly slot, recipeId and servings")
            if meal["slot"] not in SLOTS:
                raise PlannerError(f"slot must be one of {', '.join(SLOTS)}")
            if recipe_id(meal["recipeId"]) != meal["recipeId"]:
                raise PlannerError("Use canonical lowercase recipe UUIDs")
            number(meal["servings"], "meal.servings", positive=True)
            key = (meal["slot"], meal["recipeId"])
            if key in seen:
                raise PlannerError("Combine duplicate recipe/slot entries by adding servings")
            seen.add(key)
    return plan


class Client:
    def __init__(self, url, token):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise PlannerError("Norish URL must be a plain origin without credentials/path/query")
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise PlannerError("Use HTTPS, except for a loopback Norish URL")
        if not token.strip():
            raise PlannerError("Empty Norish API key")
        self.url = url.rstrip("/")
        self.token = token.strip()

    def request(self, method, path, body=None):
        payload = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = urllib.request.Request(self.url + "/api/v1" + path, data=payload, method=method,
                                         headers={"x-api-key": self.token, "Content-Type": "application/json"})
        # Never forward a key to a redirected origin (or accidentally accept a login page).
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            wait = error.headers.get("Retry-After", "unspecified")
            status = error.code
            error.close()
            suffix = f"; retry after {wait} seconds" if status == 429 else ""
            raise PlannerError(f"Norish {method} {path}: HTTP {status}{suffix}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise PlannerError(f"Norish {method} {path}: network error or invalid JSON") from None

    def recipe(self, rid):
        return self.request("GET", "/recipes/" + recipe_id(rid))


class Catalog:
    def __init__(self, path):
        data = read_json(path)
        self.recipes = {item["id"]: item for item in data["recipes"]}

    def recipe(self, rid):
        if rid not in self.recipes:
            raise PlannerError(f"Recipe {rid} not in catalog snapshot")
        return self.recipes[rid]


def nutrition_status(recipe):
    tags = {tag.get("name") for tag in recipe.get("tags", []) if isinstance(tag, dict)}
    if "planner:nutrition-estimated" in tags:
        return "estimated"
    if "planner:nutrition-verified" in tags:
        return "verified"
    return "unclassified"


def evaluate(plan, source):
    validate_plan(plan)
    recipes = {meal["recipeId"]: None for day in plan["days"] for meal in day["meals"]}
    for rid in recipes:
        recipes[rid] = source.recipe(rid)
    days, fingerprint = [], {}
    all_complete = all_within = True
    ingredient_days = {}
    unlinked = set()
    for rid, recipe in recipes.items():
        fingerprint[rid] = {key: recipe.get(key) for key in (*MACROS, "version", "updatedAt")}
        fingerprint[rid]["nutritionStatus"] = nutrition_status(recipe)
    for day in plan["days"]:
        totals = dict.fromkeys(MACROS, 0.0)
        complete = dict.fromkeys(MACROS, True)
        meals = []
        for meal in day["meals"]:
            recipe = recipes[meal["recipeId"]]
            macros, missing = {}, []
            for macro in MACROS:
                value = recipe.get(macro)
                if value is None:
                    macros[macro] = None
                    missing.append(macro)
                    complete[macro] = False
                else:
                    value = stored_macro(value, f"Recipe {meal['recipeId']} {macro}")
                    macros[macro] = round(value * meal["servings"], 4)
                    totals[macro] += value * meal["servings"]
            for ingredient in recipe.get("recipeIngredients", []):
                iid = ingredient.get("ingredientId")
                if iid:
                    entry = ingredient_days.setdefault(iid, {"name": ingredient.get("ingredientName"), "days": set(), "recipes": set()})
                    entry["days"].add(day["date"])
                    entry["recipes"].add(meal["recipeId"])
                else:
                    unlinked.add(ingredient.get("ingredientName", "unknown"))
            meals.append({**meal, "name": recipe.get("name"), "macros": macros, "missing": missing,
                          "nutritionStatus": nutrition_status(recipe)})
        totals = {macro: round(totals[macro], 4) if complete[macro] else None for macro in MACROS}
        delta = {macro: round(totals[macro] - plan["targets"][macro], 4) if complete[macro] else None for macro in MACROS}
        within = {macro: complete[macro] and abs(delta[macro]) <= plan["targets"][macro] * plan.get("tolerance", .10) + 1e-6 for macro in MACROS}
        all_complete &= all(complete.values())
        all_within &= all(within.values())
        days.append({"date": day["date"], "meals": meals, "totals": totals, "delta": delta, "withinTolerance": within})
    overlaps = [{"ingredientId": iid, "name": value["name"], "days": sorted(value["days"]), "recipeCount": len(value["recipes"])}
                for iid, value in sorted(ingredient_days.items()) if len(value["recipes"]) > 1]
    return {"targets": plan["targets"], "tolerance": plan.get("tolerance", .10), "days": days,
            "complete": bool(all_complete), "withinTolerance": bool(all_within),
            "recipeFingerprint": digest(fingerprint),
            "estimatedRecipeIds": sorted(rid for rid, recipe in recipes.items() if nutrition_status(recipe) == "estimated"),
            "ingredients": {"distinctLinked": len(ingredient_days), "sharedBetweenRecipes": overlaps,
                            "unlinkedNames": sorted(unlinked)},
            "warnings": [
                "Only listed meals/servings are evaluated; this is not an actual-intake diary.",
                "Macros are Norish's stored per-serving values, not its browser-calculated ingredient totals. Null means unknown.",
                "Nutrition labels are user-supplied provenance, not independent verification. Unclassified does not mean verified.",
                "Norish's calendar does not store planned portions. Keep the receipt as the portion manifest.",
                "Ingredient overlap uses catalogue IDs only; it is not a consolidated or pantry-adjusted shopping list."]}


def calendar(client, today):
    # REST exposes only these relative windows, not arbitrary date-range reads.
    start = today.replace(day=1)
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    monday = today - dt.timedelta(days=today.weekday())
    covered = {start + dt.timedelta(days=i) for i in range((end - start).days + 1)}
    covered.update(monday + dt.timedelta(days=i) for i in range(7))
    items = {}
    for period in ("month", "week"):
        for item in client.request("GET", "/planned-recipes/" + period):
            items[item["id"]] = item
    return items, covered


def save_receipt(path, value):
    fd, temp = tempfile.mkstemp(prefix=".norish-receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextlib.contextmanager
def receipt_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PlannerError("Another process is using this receipt") from None
        if path.is_symlink():
            raise PlannerError("Receipt must not be a symlink")
        yield


def apply_plan(plan, client, receipt_path, today, allow_outside=False, ack_estimates=False):
    report = evaluate(plan, client)  # Always re-read live recipes before writing.
    if not report["complete"]:
        raise PlannerError("Missing stored macros; inspect evaluate output. No calendar entries written.")
    if not report["withinTolerance"] and not allow_outside:
        raise PlannerError("Plan is outside target tolerance; revise it or explicitly use --allow-outside-targets")
    if report["estimatedRecipeIds"] and not ack_estimates:
        raise PlannerError("Plan includes explicitly estimated macros; review them and pass --ack-estimates to apply")
    with receipt_lock(receipt_path):
        plan_hash = digest(plan)
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if (receipt.get("schema") != 1 or receipt.get("planHash") != plan_hash
                    or receipt.get("url") != client.url or receipt.get("recipeFingerprint") != report["recipeFingerprint"]):
                raise PlannerError("Receipt does not match this plan, server, or current recipe macros/version")
            if any(item["status"] == "undone" for item in receipt["entries"]):
                raise PlannerError("This receipt was undone; use a new receipt for a new application")
        else:
            receipt = {"schema": 1, "url": client.url, "planHash": plan_hash,
                       "recipeFingerprint": report["recipeFingerprint"], "report": report,
                       "entries": [{"id": str(uuid.uuid4()), "date": day["date"], **meal, "status": "pending"}
                                   for day in plan["days"] for meal in day["meals"]]}
        existing, covered = calendar(client, today)
        owned = {entry["id"] for entry in receipt["entries"]}
        for entry in receipt["entries"]:
            if date(entry["date"]) not in covered:
                raise PlannerError("Plan date outside the API's current-month/current-week read windows; cannot safely check conflicts")
            found = existing.get(entry["id"])
            if found and any(found[key] != entry[key] for key in ("date", "slot", "recipeId")):
                raise PlannerError("A receipt entry was changed in Norish; refusing to modify the calendar")
            if entry["status"] == "applied" and not found:
                raise PlannerError("An applied entry was removed externally; refusing to silently recreate it")
            if any(item["id"] not in owned and item["date"] == entry["date"] and item["slot"] == entry["slot"] for item in existing.values()):
                raise PlannerError(f"Existing recipe in {entry['date']} {entry['slot']}; refusing to overwrite or add alongside it")
        save_receipt(receipt_path, receipt)  # Persist client-minted IDs BEFORE any writes.
        for entry in receipt["entries"]:
            if entry["id"] not in existing:
                result = client.request("POST", "/planned-recipes", {key: entry[key] for key in ("id", "date", "slot", "recipeId")})
                if result.get("id") != entry["id"]:
                    raise PlannerError("Server did not honour client ID; inspect calendar before retrying")
            entry["status"] = "applied"
            save_receipt(receipt_path, receipt)
        return receipt


def undo(client, receipt_path, today):
    with receipt_lock(receipt_path):
        receipt = read_json(receipt_path)
        if receipt.get("schema") != 1 or receipt.get("url") != client.url:
            raise PlannerError("Receipt server/schema mismatch")
        existing, covered = calendar(client, today)
        for entry in receipt["entries"]:
            if date(entry["date"]) not in covered:
                raise PlannerError("Receipt dates outside readable calendar windows; undo manually in Norish")
            found = existing.get(entry["id"])
            if found and any(found[key] != entry[key] for key in ("date", "slot", "recipeId")):
                raise PlannerError("A receipt entry changed externally; refusing undo")
        for entry in receipt["entries"]:
            found = existing.get(entry["id"])
            if found and entry["status"] != "undone":
                result = client.request("DELETE", f"/planned-recipes/{entry['id']}?version={found['version']}")
                if result.get("stale") or not result.get("success"):
                    raise PlannerError("Concurrent calendar update; undo stopped. Recheck before retrying.")
            entry["status"] = "undone"
            save_receipt(receipt_path, receipt)
        return receipt


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise PlannerError(f"{label} must be nonempty text")
    return value.strip()


def public_url(value):
    value = text(value, "URL")
    parsed = urllib.parse.urlsplit(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password
            or host == "localhost" or host.endswith((".localhost", ".local", ".internal"))):
        raise PlannerError("Use a public HTTP(S) URL without embedded credentials")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise PlannerError("Private/local import addresses are not allowed")
    if address is None and ("." not in host or host.replace(".", "").isdigit()):
        raise PlannerError("Use a public fully-qualified hostname, not a local/ambiguous address")
    if any(ord(char) < 32 for char in value):
        raise PlannerError("URL must not contain control characters")
    return value


def recipe_template():
    return {"name": "Lentil and spinach bowl", "servings": 2, "systemUsed": "metric",
            "ingredients": [{"name": "cooked lentils", "amount": 300, "unit": "g"},
                            {"name": "spinach", "amount": 100, "unit": "g"}],
            "steps": ["Warm the lentils, stir in the spinach and cook until wilted."],
            "categories": ["Dinner"], "tags": ["weeknight"],
            "notes": "Example only. Quantities describe the whole recipe; no macros are supplied."}


def prepare_recipe(data):
    allowed = {"name", "servings", "systemUsed", "ingredients", "steps", "categories", "tags",
               "description", "notes", "url", "prepMinutes", "cookMinutes", "totalMinutes", "nutrition"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise PlannerError("Recipe has unsupported fields; start with recipe-template")
    servings = data.get("servings")
    if isinstance(servings, bool) or not isinstance(servings, int) or not 1 <= servings <= 2147483647:
        raise PlannerError("Recipe servings must be a positive integer (whole-recipe yield)")
    system = data.get("systemUsed", "metric")
    if system not in ("metric", "us"):
        raise PlannerError("systemUsed must be metric or us")
    payload = {"name": text(data.get("name"), "Recipe name"), "servings": servings,
               "systemUsed": system, "recipeIngredients": [], "steps": [], "tags": []}
    for field in ("description", "notes"):
        if field in data and data[field] is not None:
            if not isinstance(data[field], str):
                raise PlannerError(f"{field} must be text")
            payload[field] = data[field]
    if data.get("url") is not None:
        payload["url"] = public_url(data["url"])
    for field in ("prepMinutes", "cookMinutes", "totalMinutes"):
        if data.get(field) is not None:
            value = data[field]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2147483647:
                raise PlannerError(f"{field} must be a nonnegative integer")
            payload[field] = value
    ingredients = data.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        raise PlannerError("ingredients must be a nonempty list")
    for order, ingredient in enumerate(ingredients):
        if not isinstance(ingredient, dict) or set(ingredient) - {"name", "amount", "unit", "ingredientId"}:
            raise PlannerError("Each ingredient supports name, amount, unit and optional ingredientId")
        amount = ingredient.get("amount")
        if amount is not None:
            number(amount, "Ingredient amount", positive=True)
        unit = ingredient.get("unit")
        if unit is not None:
            unit = text(unit, "Ingredient unit")
        iid = ingredient.get("ingredientId")
        if iid is not None:
            iid = recipe_id(iid)
        payload["recipeIngredients"].append({"ingredientName": text(ingredient.get("name"), "Ingredient name"),
                                              "amount": amount, "unit": unit, "ingredientId": iid,
                                              "order": order, "systemUsed": system})
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PlannerError("steps must be a nonempty list of instruction strings")
    payload["steps"] = [{"step": text(step, "Step"), "order": order, "systemUsed": system}
                        for order, step in enumerate(steps)]
    categories = data.get("categories", [])
    if not isinstance(categories, list) or any(category not in SLOTS for category in categories):
        raise PlannerError(f"categories must be a list from {', '.join(SLOTS)}")
    payload["categories"] = categories
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        raise PlannerError("tags must be a list of strings")
    for tag in tags:
        tag = text(tag, "Tag")
        if tag.lower().startswith("planner:nutrition-"):
            raise PlannerError("Nutrition tags are reserved; supply nutrition metadata instead")
        payload["tags"].append({"name": tag})
    nutrition = data.get("nutrition")
    if nutrition is not None:
        if not isinstance(nutrition, dict) or set(nutrition) != {"status", "source", "perServing"}:
            raise PlannerError("nutrition must have exactly status, source and perServing")
        status = nutrition["status"]
        if status not in ("estimated", "verified"):
            raise PlannerError("nutrition.status must be estimated or verified; never label an AI guess verified")
        source = text(nutrition["source"], "Nutrition source/basis")
        macros = nutrition["perServing"]
        if not isinstance(macros, dict) or set(macros) != set(MACROS):
            raise PlannerError("nutrition.perServing must specify calories, fat, carbs, protein; use null for unknown")
        for macro, value in macros.items():
            if value is None:
                payload[macro] = None
                continue
            number(value, f"nutrition.perServing.{macro}")
            if macro == "calories":
                if value != int(value) or value > 2147483647:
                    raise PlannerError("Calories must be a nonnegative integer or null")
                payload[macro] = int(value)
            else:
                if value > 9999.99:
                    raise PlannerError(f"{macro} exceeds Norish's numeric field limit")
                payload[macro] = f"{value:.2f}"
        payload["tags"].append({"name": f"planner:nutrition-{status}"})
        annotation = f"[norish-planner nutrition]\nStatus: {status}\nBasis: {source}\nValues supplied per serving; not independently verified by this tool.\n[/norish-planner nutrition]"
        payload["notes"] = (payload.get("notes", "").rstrip() + "\n\n" + annotation).strip()
    return payload


def submit_recipe(client, operation, payload, receipt_path):
    # Create is asynchronous; imports do not accept client idempotency keys.
    # Even a 404 after a timeout cannot prove the write was never accepted.
    with receipt_lock(receipt_path):
        request_hash = digest(payload)
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if (receipt.get("schema") != "recipe-write-v1" or receipt.get("url") != client.url
                    or receipt.get("operation") != operation or receipt.get("requestHash") != request_hash):
                raise PlannerError("Recipe-write receipt belongs to another request/server")
            return {**receipt, "resubmitted": False,
                    "warning": "Never automatically resubmitted. Check status/recipe or search Norish before attempting a new request."}
        body = dict(payload)
        receipt = {"schema": "recipe-write-v1", "url": client.url, "operation": operation,
                   "requestHash": request_hash, "status": "uncertain", "recipeIds": []}
        if operation == "create":
            body["id"] = str(uuid.uuid4())
            receipt["recipeIds"] = [body["id"]]
        save_receipt(receipt_path, receipt)  # Durable intent before the nontransactional write.
        paths = {"create": "/recipes", "import-url": "/recipes/import/url", "import-text": "/recipes/import/paste"}
        result = client.request("POST", paths[operation], body)
        if operation == "create":
            if result != body["id"]:
                raise PlannerError("Unexpected create response; inspect the receipt ID/library before retrying")
        elif operation == "import-url":
            receipt["recipeIds"] = [recipe_id(result["recipeId"])]
        else:
            receipt["recipeIds"] = [recipe_id(rid) for rid in result["recipeIds"]]
        receipt["status"] = "submitted"
        receipt["result"] = result
        receipt["warning"] = "Accepted is not necessarily saved: check status for each recipe ID, then read the full recipe."
        save_receipt(receipt_path, receipt)
        return receipt


class Fdc:
    def __init__(self, key):
        key = key.strip()
        if not key or key == "DEMO_KEY":
            raise PlannerError("USDA DEMO_KEY returns scrubbed nutrient values. Create a free key at "
                               "https://api.data.gov/signup/ and store it in "
                               "~/.config/norish-planner/usda-key (mode 0600)")
        self.key = key

    def get(self, path, params):
        query = urllib.parse.urlencode({**params, "api_key": self.key})
        request = urllib.request.Request(f"{FDC_BASE}{path}?{query}")
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            status, wait = error.code, error.headers.get("Retry-After", "unspecified")
            error.close()
            suffix = f"; retry after {wait} seconds" if status == 429 else ""
            raise PlannerError(f"USDA {path}: HTTP {status}{suffix}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise PlannerError(f"USDA {path}: network error or invalid JSON") from None


def fdc_search(fdc, query, kind="GENERAL"):
    data = fdc.get("/fdc/v1/foods/search", {"query": query, "queryType": kind, "pageSize": 20})
    return [{"fdcId": item["fdcId"], "description": item.get("description"),
             "dataType": item.get("dataType"), "brandName": item.get("brandName")}
            for item in data.get("foods", [])]


def fdc_food(fdc, fdcid):
    fdcid = int(fdcid)
    data = fdc.get(f"/fdc/v1/food/{fdcid}", {})
    if not data or data.get("fdcId") is None:
        raise PlannerError(f"USDA has no food record {fdcid}")
    # USDA returns foodNutrients[].amount already normalised to per-100-g for
    # Foundation, SR Legacy, Survey and Branded records alike, so no portion
    # conversion is performed. Portions are reported for context only.
    values, unknown = {}, list(MACROS)
    for entry in data.get("foodNutrients") or []:
        nutrient = entry.get("nutrient") or {}
        macro = next((name for name, nid in FDC_NUTRIENT_IDS.items() if nid == nutrient.get("id")), None)
        if macro is None:
            continue
        value = entry.get("amount")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            values[macro] = float(value)
            unknown.remove(macro)
    return {"fdcId": data["fdcId"], "description": data.get("description"), "dataType": data.get("dataType"),
            "brandName": data.get("brandName"), "portionBasis": "per-100g",
            "per100g": values if len(values) == len(MACROS) else (values or None),
            "missingNutrients": sorted(unknown),
            "portions": [{"sequenceNumber": p.get("sequenceNumber"), "gramWeight": p.get("gramWeight"),
                          "amount": p.get("amount"), "unit": (p.get("measureUnit") or {}).get("name")}
                         for p in (data.get("foodPortions") or []) if isinstance(p, dict)][:6]}


def load_matches(path):
    if not path.exists():
        return {}
    data = read_json(path)
    if not isinstance(data, dict) or "matches" not in data:
        raise PlannerError("Matches file must be an object containing a matches map")
    return {name.lower(): value for name, value in data["matches"].items() if isinstance(value, dict)}


def fdc_calc(recipe, matches, get_food):
    servings = number(recipe.get("servings"), "Recipe servings", positive=True)
    if not isinstance(servings, int) or isinstance(servings, bool):
        raise PlannerError("Recipe servings must be a positive integer")
    totals, unquantified, unmatched, notes = dict.fromkeys(MACROS, 0.0), [], [], []
    lines = recipe.get("recipeIngredients") or recipe.get("ingredients") or []
    for ingredient in lines:
        name = (ingredient.get("ingredientName") or ingredient.get("name") or "").strip().lower()
        amount, unit = ingredient.get("amount"), (ingredient.get("unit") or "").strip().lower()
        match = matches.get(name)
        if not match:
            unmatched.append(name or "(unnamed)")
            continue
        if amount is None:
            unquantified.append({"name": name, "reason": "no amount"})
            continue
        grams = float(amount) * MASS_UNITS.get(unit, 1) if unit in MASS_UNITS else None
        density = match.get("densityGPerMl")
        if grams is None and unit in VOLUME_UNITS and density:
            grams = float(amount) * VOLUME_UNITS[unit] * density
        if grams is None:
            unquantified.append({"name": name, "reason": f"unit {unit or 'none'} not convertible to grams"})
            continue
        per100g = match.get("per100g")
        if not per100g:
            fetched = get_food(match["fdcId"]) if match.get("fdcId") else None
            if not fetched or not fetched.get("per100g"):
                unquantified.append({"name": name, "reason": "USDA record lacks macro values; supply --per-100g from a reviewed label"})
                continue
            per100g = fetched["per100g"]
            notes.append({"name": name, "fdcId": fetched["fdcId"], "description": fetched["description"],
                          "dataType": fetched.get("dataType"), "brandName": fetched.get("brandName")})
        else:
            notes.append({"name": name, "fdcId": match.get("fdcId"), "per100g": per100g})
        for macro in MACROS:
            if macro in per100g:
                totals[macro] += per100g[macro] * grams / 100
    per_serving = {macro: round(totals[macro] / servings, 2) for macro in MACROS}
    return {"servings": servings, "perServing": per_serving,
            "complete": not (unmatched or unquantified),
            "unmatchedIngredients": sorted(set(unmatched)),
            "unquantifiedIngredients": unquantified,
            "sources": notes,
            "warnings": ["USDA values are per matched food record and portion; preparation (cooked rice, drained "
                         "cans, reduction) can differ materially.",
                         "A missing ingredient makes the totals incomplete, not zero."]}


def get_fdc(args):
    key = os.environ.get("USDA_API_KEY")
    if not key:
        path = Path(args.usda_key_file).expanduser()
        if not path.is_file():
            raise PlannerError(f"Create a free key at https://api.data.gov/signup/; store it in {path} (mode 0600)")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise PlannerError("USDA key file must not be accessible to group/others; chmod 600 it")
        key = path.read_text()
    return Fdc(key)


def get_client(args):
    token = os.environ.get("NORISH_API_KEY")
    if not token:
        path = Path(args.token_file).expanduser()
        if not path.is_file():
            raise PlannerError(f"Create an API key in Norish Settings > User > API keys; store it in {path} (mode 0600)")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise PlannerError("API key file must not be accessible to group/others; chmod 600 it")
        token = path.read_text()
    return Client(args.url, token)


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog="norish-planner", description=__doc__)
    parser.add_argument("--url", default=os.environ.get("NORISH_URL", DEFAULT_URL))
    parser.add_argument("--token-file", default="~/.config/norish-planner/api-key")
    sub = parser.add_subparsers(dest="command", required=True)
    cat = sub.add_parser("catalog", help="Read a page of full recipes, including stored macros and ingredients")
    cat.add_argument("--search")
    cat.add_argument("--tag", action="append", default=[])
    cat.add_argument("--limit", type=int, default=50, choices=range(1, 201), metavar="1..200")
    cat.add_argument("--cursor", type=int, default=0)
    cat.add_argument("--max-minutes", type=int)
    get = sub.add_parser("recipe")
    get.add_argument("id")
    sub.add_parser("calendar", help="Read current week/month recipe entries")
    check = sub.add_parser("evaluate", help="Read-only macro and ingredient-overlap report")
    check.add_argument("plan")
    check.add_argument("--catalog", help="Evaluate offline against a catalog snapshot instead of live API")
    apply = sub.add_parser("apply", help="Explicit calendar writes; requires approval and a persistent receipt")
    apply.add_argument("plan")
    apply.add_argument("--receipt", required=True)
    apply.add_argument("--confirm", action="store_true", help="Human-approved calendar write")
    apply.add_argument("--ack-portions", action="store_true", help="Acknowledge portions live in the receipt, NOT Norish's calendar")
    apply.add_argument("--allow-outside-targets", action="store_true")
    apply.add_argument("--ack-estimates", action="store_true", help="Acknowledge any recipes explicitly labelled with estimated macros")
    remove = sub.add_parser("undo", help="Remove only entries belonging to an apply receipt")
    remove.add_argument("--receipt", required=True)
    remove.add_argument("--confirm", action="store_true")
    sub.add_parser("recipe-template", help="Print a structured recipe input example; no API calls")
    create = sub.add_parser("create", help="Preview a structured recipe, or submit with --confirm and --receipt")
    create.add_argument("file")
    url_import = sub.add_parser("import-url", help="Preview or queue a recipe URL import")
    url_import.add_argument("source_url", metavar="URL")
    text_import = sub.add_parser("import-text", help="Preview or import a file containing text, JSON-LD or YAML")
    text_import.add_argument("file")
    for command in (create, url_import, text_import):
        command.add_argument("--confirm", action="store_true", help="User-approved recipe write; otherwise preview only")
        command.add_argument("--receipt", help="Persistent receipt required for writes; never auto-resubmits")
    for command in (url_import, text_import):
        command.add_argument("--force-ai", action="store_true", help="Explicitly request Norish's configured AI parser (may incur costs)")
    status = sub.add_parser("status", help="Read import/create status for a recipe UUID; no writes")
    status.add_argument("id")
    parser.add_argument("--usda-key-file", default="~/.config/norish-planner/usda-key")
    search = sub.add_parser("fdc-search", help="Search USDA FoodData Central for candidate food matches")
    search.add_argument("query")
    search.add_argument("--type", choices=("GENERAL", "BRANDED", "ALL"), default="GENERAL")
    food = sub.add_parser("fdc-food", help="Read one USDA food record and convert macros to per-100 g")
    food.add_argument("fdc_id", type=int)
    show = sub.add_parser("fdc-matches", help="Show the local ingredient-to-USDA match store")
    show.add_argument("--matches", default="~/.config/norish-planner/usda-matches.json")
    add = sub.add_parser("fdc-add-match", help="Record a reviewed ingredient-to-USDA match")
    add.add_argument("name")
    add.add_argument("fdc_id", type=int)
    add.add_argument("--matches", default="~/.config/norish-planner/usda-matches.json")
    add.add_argument("--per-100g", help="Override per-100 g JSON if the record's portion is unusable")
    add.add_argument("--density", type=float, help="g/ml for volume-based ingredients")
    calc = sub.add_parser("fdc-calc", help="Compute recipe macros from matched ingredients (read-only)")
    calc.add_argument("file")
    calc.add_argument("--matches", default="~/.config/norish-planner/usda-matches.json")
    args = parser.parse_args(argv)
    try:
        if args.command in ("apply", "undo") and not args.confirm:
            raise PlannerError("Write operation requires --confirm after user approval")
        if args.command == "apply" and not args.ack_portions:
            raise PlannerError("Norish cannot store planned portions; keep the receipt and pass --ack-portions")
        if args.command == "recipe-template":
            print(json.dumps(recipe_template(), indent=2))
            return 0
        recipe_write = args.command in ("create", "import-url", "import-text")
        payload = None
        if recipe_write:
            if args.command == "create":
                payload = prepare_recipe(read_json(args.file))
            elif args.command == "import-url":
                payload = {"url": public_url(args.source_url), "forceAI": args.force_ai}
            else:
                pasted = Path(args.file).read_text()
                if not pasted.strip() or len(pasted) > 100000:
                    raise PlannerError("Import text must be nonempty and at most 100,000 characters total")
                payload = {"text": pasted, "forceAI": args.force_ai}
            if not args.confirm:
                print(json.dumps({"preview": True, "operation": args.command, "payload": payload,
                                  "warning": "Nothing written. Imports may use configured AI and automatic enrichment; imported nutrition is not independently verified."}, indent=2))
                return 0
            if not args.receipt:
                raise PlannerError("Recipe writes require --receipt as well as --confirm")
        plan = validate_plan(read_json(args.plan)) if args.command in ("evaluate", "apply") else None
        client = Catalog(args.catalog) if args.command == "evaluate" and args.catalog else get_client(args)
        today = dt.datetime.now(ZoneInfo("America/New_York")).date()  # Matches Blade/Norish TZ.
        if args.command == "catalog":
            if args.cursor < 0 or (args.max_minutes is not None and args.max_minutes < 1):
                raise PlannerError("cursor must be nonnegative and max-minutes positive")
            body = {"limit": args.limit, "cursor": args.cursor, "tags": args.tag, "filterMode": "AND"}
            if args.search:
                body["search"] = args.search
            if args.max_minutes is not None:
                body["maxCookingTime"] = args.max_minutes
            page = client.request("POST", "/recipes/search", body)
            result = {"recipes": [client.recipe(item["id"]) for item in page["recipes"]],
                      "total": page["total"], "nextCursor": page["nextCursor"],
                      "macroSource": "stored-per-serving; null is unknown"}
        elif args.command == "recipe":
            result = client.recipe(args.id)
        elif args.command == "status":
            result = client.request("GET", "/recipes/import/status/" + recipe_id(args.id))
        elif args.command == "fdc-search":
            result = {"query": args.query, "type": args.type,
                      "candidates": fdc_search(get_fdc(args), args.query, args.type)}
        elif args.command == "fdc-food":
            result = fdc_food(get_fdc(args), args.fdc_id)
        elif args.command == "fdc-matches":
            result = load_matches(Path(args.matches).expanduser())
        elif args.command == "fdc-add-match":
            matches_path = Path(args.matches).expanduser()
            record = {"fdcId": args.fdc_id}
            if args.per_100g:
                try:
                    override = json.loads(args.per_100g)
                except json.JSONDecodeError:
                    raise PlannerError("--per-100g must be inline JSON, for example '{\"calories\":250}'") from None
                if not isinstance(override, dict) or set(override) - set(MACROS) or any(
                        not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 for v in override.values()):
                    raise PlannerError("--per-100g must be JSON with nonnegative calories/fat/carbs/protein")
                record["per100g"] = {key: float(value) for key, value in override.items()}
            else:
                fetched = fdc_food(get_fdc(args), args.fdc_id)
                if not fetched.get("per100g"):
                    raise PlannerError("USDA record lacks macro values; supply --per-100g from a reviewed label")
                record["per100g"] = fetched["per100g"]
                record["description"] = fetched["description"]
                record["dataType"] = fetched["dataType"]
                if fetched.get("brandName"):
                    record["brandName"] = fetched["brandName"]
            if args.density:
                number(args.density, "density", positive=True)
                record["densityGPerMl"] = args.density
            matches = load_matches(matches_path)
            matches[args.name.strip().lower()] = record
            save_receipt(matches_path, {"matches": matches})
            result = {"saved": str(matches_path), "name": args.name.strip().lower(), "record": record}
        elif args.command == "fdc-calc":
            result = fdc_calc(read_json(args.file), load_matches(Path(args.matches).expanduser()),
                              lambda fid: fdc_food(get_fdc(args), fid))
        elif recipe_write:
            result = submit_recipe(client, args.command, payload, Path(args.receipt).expanduser())
        elif args.command == "calendar":
            items, _ = calendar(client, today)
            result = {"recipes": list(items.values()), "warning": "Current month/week only; notes and portion overrides are not exposed"}
        elif args.command == "evaluate":
            result = evaluate(plan, client)
        elif args.command == "apply":
            result = apply_plan(plan, client, Path(args.receipt).expanduser(), today, args.allow_outside_targets, args.ack_estimates)
        else:
            result = undo(client, Path(args.receipt).expanduser(), today)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (PlannerError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
