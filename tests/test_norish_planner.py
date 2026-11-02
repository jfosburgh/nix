"""Offline planning and failure/retry safety tests. No live data or credentials."""
import copy
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("norish_planner", Path(__file__).resolve().parents[1] / "scripts/norish-planner.py")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)
RID = "11111111-1111-4111-8111-111111111111"
RID2 = "22222222-2222-4222-8222-222222222222"
TODAY = dt.date(2026, 11, 15)


class FakeClient:
    url = "https://norish.example"

    def __init__(self):
        self.recipes = {RID: {"id": RID, "name": "Lunch", "servings": 4,
                             "calories": 400, "fat": 10, "carbs": 40, "protein": 30,
                             "version": 1, "recipeIngredients": [
                                 {"ingredientId": "onion", "ingredientName": "onion"},
                                 {"ingredientId": None, "ingredientName": "salt to taste"}]}}
        self.items = {}
        self.writes = []
        self.fail_after_write = False
        self.stale = False

    def recipe(self, rid):
        return copy.deepcopy(self.recipes[rid])

    def request(self, method, path, body=None):
        if method == "GET":
            return list(copy.deepcopy(self.items).values())
        self.writes.append((method, path, copy.deepcopy(body)))
        if method == "POST":
            if body["id"] in self.items:
                raise AssertionError("Duplicate create attempted")
            self.items[body["id"]] = {**body, "version": 1}
            if self.fail_after_write:
                self.fail_after_write = False
                raise planner.PlannerError("Simulated lost response AFTER server committed")
            return {"id": body["id"]}
        if method == "DELETE":
            if self.stale:
                return {"success": True, "stale": True}
            del self.items[path.split("/")[-1].split("?")[0]]
            return {"success": True, "stale": False}
        raise AssertionError(method)


def plan():
    return {"targets": {"calories": 800, "fat": 20, "carbs": 80, "protein": 60},
            "tolerance": 0.05,
            "days": [{"date": TODAY.isoformat(), "meals": [
                {"slot": "Lunch", "recipeId": RID, "servings": 2}]}]}


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.receipt = Path(self.tmp.name) / "receipts/plan.json"
        self.client = FakeClient()
        self.plan = plan()

    def test_macros_are_per_serving_not_per_batch(self):
        report = planner.evaluate(self.plan, self.client)
        self.assertEqual(report["days"][0]["totals"], self.plan["targets"])
        self.assertTrue(report["withinTolerance"])
        self.assertTrue(report["complete"])
        self.assertEqual(report["ingredients"]["unlinkedNames"], ["salt to taste"])
        self.assertEqual(self.client.writes, [])

    def test_live_api_decimal_strings(self):
        for macro in planner.MACROS:
            self.client.recipes[RID][macro] = str(self.client.recipes[RID][macro])
        report = planner.evaluate(self.plan, self.client)
        self.assertTrue(report["withinTolerance"])
        self.assertEqual(report["days"][0]["totals"], self.plan["targets"])
        self.client.recipes[RID]["fat"] = "0.00"
        self.plan["targets"]["fat"] = 0
        self.assertTrue(planner.evaluate(self.plan, self.client)["withinTolerance"])

    def test_invalid_stored_macro_strings(self):
        for value in ("NaN", "Infinity", "-1", "8 g", ""):
            self.client.recipes[RID]["fat"] = value
            with self.subTest(value=value), self.assertRaises(planner.PlannerError):
                planner.evaluate(self.plan, self.client)

    def test_unknown_is_not_zero_and_apply_refuses(self):
        self.client.recipes[RID]["protein"] = None
        report = planner.evaluate(self.plan, self.client)
        self.assertIsNone(report["days"][0]["totals"]["protein"])
        self.assertIsNone(report["days"][0]["delta"]["protein"])
        self.assertFalse(report["complete"])
        with self.assertRaisesRegex(planner.PlannerError, "Missing stored macros"):
            planner.apply_plan(self.plan, self.client, self.receipt, TODAY, allow_outside=True)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.client.writes, [])

    def test_zero_macro_is_known(self):
        self.client.recipes[RID]["fat"] = 0
        self.plan["targets"]["fat"] = 0
        self.assertTrue(planner.evaluate(self.plan, self.client)["withinTolerance"])

    def test_invalid_plans(self):
        changes = [lambda p: p.update(tolerance=-1),
                   lambda p: p["targets"].update(protein=float("nan")),
                   lambda p: p["targets"].update(fat=True),
                   lambda p: p["days"][0].update(date="2026-02-30"),
                   lambda p: p["days"][0]["meals"][0].update(servings=0),
                   lambda p: p["days"][0]["meals"][0].update(servings=float("inf")),
                   lambda p: p["days"][0]["meals"][0].update(recipeId="bad"),
                   lambda p: p["days"].append(copy.deepcopy(p["days"][0])),
                   lambda p: p["days"][0]["meals"].append(copy.deepcopy(p["days"][0]["meals"][0]))]
        for change in changes:
            candidate = plan()
            change(candidate)
            with self.subTest(candidate=candidate), self.assertRaises(planner.PlannerError):
                planner.validate_plan(candidate)

    def test_overlap_uses_ids_not_names(self):
        self.client.recipes[RID2] = {**copy.deepcopy(self.client.recipes[RID]), "id": RID2}
        self.plan["days"][0]["meals"].append({"slot": "Dinner", "recipeId": RID2, "servings": 1})
        report = planner.evaluate(self.plan, self.client)
        self.assertEqual(report["ingredients"]["distinctLinked"], 1)
        self.assertEqual(report["ingredients"]["sharedBetweenRecipes"][0]["recipeCount"], 2)

    def test_target_failure_needs_explicit_override(self):
        self.plan["targets"]["calories"] = 2000
        with self.assertRaisesRegex(planner.PlannerError, "outside target"):
            planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.assertEqual(self.client.writes, [])
        planner.apply_plan(self.plan, self.client, self.receipt, TODAY, allow_outside=True)
        self.assertEqual(len(self.client.writes), 1)

    def test_apply_is_retryable_and_keeps_portions(self):
        result = planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.assertEqual(result["entries"][0]["servings"], 2)
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("servings", self.client.writes[0][2])
        planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.assertEqual(len(self.client.writes), 1)

    def test_lost_response_does_not_duplicate_on_retry(self):
        self.client.fail_after_write = True
        with self.assertRaises(planner.PlannerError):
            planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.assertEqual(planner.read_json(self.receipt)["entries"][0]["status"], "pending")
        planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(planner.read_json(self.receipt)["entries"][0]["status"], "applied")

    def test_partial_multimeal_plan_resumes_without_duplicate(self):
        self.plan["days"][0]["meals"][0]["servings"] = 1
        self.plan["days"][0]["meals"].append({"slot": "Dinner", "recipeId": RID, "servings": 1})
        self.client.fail_after_write = True
        with self.assertRaises(planner.PlannerError):
            planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.assertEqual(len(self.client.items), 2)
        self.assertEqual(len(self.client.writes), 2)
        self.assertTrue(all(entry["status"] == "applied" for entry in planner.read_json(self.receipt)["entries"]))

    def test_conflicts_and_unreadable_dates_fail_before_writing(self):
        self.client.items["other"] = {"id": "other", "date": TODAY.isoformat(), "slot": "Lunch", "recipeId": RID2}
        with self.assertRaisesRegex(planner.PlannerError, "Existing recipe"):
            planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.assertFalse(self.receipt.exists())
        self.client.items.clear()
        self.plan["days"][0]["date"] = "2027-01-01"
        with self.assertRaisesRegex(planner.PlannerError, "outside"):
            planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.assertEqual(self.client.writes, [])

    def test_changed_plan_recipe_or_calendar_refuses_retry(self):
        planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.client.recipes[RID]["version"] = 2
        with self.assertRaisesRegex(planner.PlannerError, "Receipt does not match"):
            planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.client.recipes[RID]["version"] = 1
        self.client.items.clear()
        with self.assertRaisesRegex(planner.PlannerError, "removed externally"):
            planner.apply_plan(self.plan, self.client, self.receipt, TODAY)

    def test_undo_only_deletes_receipt_entries_and_checks_versions(self):
        planner.apply_plan(self.plan, self.client, self.receipt, TODAY)
        self.client.items["unrelated"] = {"id": "unrelated", "date": TODAY.isoformat(), "slot": "Dinner", "recipeId": RID2}
        self.client.stale = True
        with self.assertRaisesRegex(planner.PlannerError, "Concurrent"):
            planner.undo(self.client, self.receipt, TODAY)
        self.assertEqual(len(self.client.items), 2)
        self.client.stale = False
        planner.undo(self.client, self.receipt, TODAY)
        self.assertEqual(list(self.client.items), ["unrelated"])
        self.assertIn("version=1", self.client.writes[-1][1])
        planner.undo(self.client, self.receipt, TODAY)
        with self.assertRaisesRegex(planner.PlannerError, "undone"):
            planner.apply_plan(self.plan, self.client, self.receipt, TODAY)

    def test_offline_catalog(self):
        path = Path(self.tmp.name) / "catalog.json"
        path.write_text(json.dumps({"recipes": list(self.client.recipes.values())}))
        self.assertTrue(planner.evaluate(self.plan, planner.Catalog(path))["complete"])

    def test_offline_cli_returns_machine_readable_report_without_credentials(self):
        catalog = Path(self.tmp.name) / "catalog.json"
        menu = Path(self.tmp.name) / "plan.json"
        catalog.write_text(json.dumps({"recipes": list(self.client.recipes.values())}))
        menu.write_text(json.dumps(self.plan))
        with patch.object(planner, "get_client", side_effect=AssertionError("no API")), patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(planner.main(["evaluate", str(menu), "--catalog", str(catalog)]), 0)
            self.assertTrue(json.loads(output.getvalue())["withinTolerance"])

    def test_cli_writes_require_approval_before_network(self):
        with patch.object(planner, "get_client", side_effect=AssertionError("must not call API")):
            self.assertEqual(planner.main(["apply", "absent.json", "--receipt", str(self.receipt)]), 1)
            self.assertEqual(planner.main(["undo", "--receipt", str(self.receipt)]), 1)

    def test_client_rejects_insecure_or_credentialed_origins(self):
        for url in ("http://example.com", "https://user:pass@example.com", "https://example.com?key=secret"):
            with self.assertRaises(planner.PlannerError):
                planner.Client(url, "secret")
        self.assertEqual(planner.Client("http://127.0.0.1:3002", "secret").url, "http://127.0.0.1:3002")

    def test_http_errors_do_not_expose_key_and_do_not_retry_writes(self):
        client = planner.Client("https://norish.example", "secret-key")
        error = urllib.error.HTTPError(client.url, 429, "rate limit", {"Retry-After": "60"}, None)
        with patch("urllib.request.build_opener") as build:
            build.return_value.open.side_effect = error
            with self.assertRaisesRegex(planner.PlannerError, "retry after 60") as result:
                client.request("POST", "/planned-recipes", {})
            self.assertNotIn("secret-key", str(result.exception))
            self.assertEqual(build.return_value.open.call_count, 1)


class RecipeWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.receipt = Path(self.tmp.name) / "create.json"
        self.client = FakeClient()
        self.data = planner.recipe_template()
        self.calls = []

        def request(method, path, body=None):
            self.calls.append((method, path, body))
            if path == "/recipes":
                return body["id"]  # Create returns a bare UUID, not an object.
            if path == "/recipes/import/url":
                return {"recipeId": RID, "status": "queued"}
            if path == "/recipes/import/paste":
                return {"recipeIds": [RID, RID2]}
            return {"recipeId": RID, "status": "completed"}
        self.client.request = request

    def test_template_maps_to_api_ingredient_and_step_schema(self):
        payload = planner.prepare_recipe(self.data)
        self.assertEqual(payload["servings"], 2)
        self.assertEqual(payload["recipeIngredients"][0], {
            "ingredientName": "cooked lentils", "amount": 300, "unit": "g", "ingredientId": None,
            "order": 0, "systemUsed": "metric"})
        self.assertEqual(payload["steps"][0]["systemUsed"], "metric")
        self.assertNotIn("calories", payload)
        self.assertNotIn("ingredients", payload)

    def test_macros_are_explicit_per_serving_and_labelled(self):
        self.data["nutrition"] = {"status": "estimated", "source": "Agent estimate; review needed",
                                  "perServing": {"calories": 400, "fat": 8.6, "carbs": 50, "protein": None}}
        payload = planner.prepare_recipe(self.data)
        self.assertEqual(payload["fat"], "8.60")
        self.assertIsNone(payload["protein"])
        self.assertIn("Agent estimate; review needed", payload["notes"])
        self.assertEqual(planner.nutrition_status(payload), "estimated")
        self.data["nutrition"]["status"] = "verified"
        self.assertEqual(planner.nutrition_status(planner.prepare_recipe(self.data)), "verified")

    def test_invalid_inputs_fail_locally(self):
        changes = [lambda d: d.update(servings=0), lambda d: d.update(servings=True),
                   lambda d: d.update(servings=1.5), lambda d: d.update(ingredients=[]),
                   lambda d: d.update(steps=[]), lambda d: d.update(calories=500),
                   lambda d: d.update(tags=["planner:nutrition-verified"]),
                   lambda d: d.update(categories=["Supper"]), lambda d: d.update(prepMinutes=-1),
                   lambda d: d["ingredients"][0].update(amount=float("nan")),
                   lambda d: d.update(nutrition={"status": "verified"})]
        for change in changes:
            candidate = planner.recipe_template()
            change(candidate)
            with self.subTest(candidate=candidate), self.assertRaises(planner.PlannerError):
                planner.prepare_recipe(candidate)

    def test_create_receipt_prevents_automatic_resubmission(self):
        payload = planner.prepare_recipe(self.data)
        first = planner.submit_recipe(self.client, "create", payload, self.receipt)
        self.assertEqual(first["status"], "submitted")
        self.assertEqual(first["recipeIds"], [self.calls[0][2]["id"]])
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)
        planner.submit_recipe(self.client, "create", payload, self.receipt)
        self.assertEqual(len(self.calls), 1)
        payload["name"] = "Another recipe"
        with self.assertRaisesRegex(planner.PlannerError, "another request"):
            planner.submit_recipe(self.client, "create", payload, self.receipt)

    def test_uncertain_create_is_not_resubmitted_even_if_not_yet_visible(self):
        def lost_response(*args):
            raise planner.PlannerError("timeout")
        self.client.request = lost_response
        payload = planner.prepare_recipe(self.data)
        with self.assertRaises(planner.PlannerError):
            planner.submit_recipe(self.client, "create", payload, self.receipt)
        receipt = planner.read_json(self.receipt)
        self.assertEqual(receipt["status"], "uncertain")
        self.assertEqual(len(receipt["recipeIds"]), 1)
        result = planner.submit_recipe(self.client, "create", payload, self.receipt)
        self.assertFalse(result["resubmitted"])

    def test_import_url_and_multiple_pasted_recipes(self):
        result = planner.submit_recipe(self.client, "import-url", {"url": "https://example.org/recipe"}, self.receipt)
        self.assertEqual(result["recipeIds"], [RID])
        self.assertEqual(self.calls[-1][1], "/recipes/import/url")
        result = planner.submit_recipe(self.client, "import-text", {"text": "recipe text"}, self.receipt.with_name("paste.json"))
        self.assertEqual(result["recipeIds"], [RID, RID2])
        self.assertEqual(self.calls[-1][1], "/recipes/import/paste")

    def test_previews_and_template_never_authenticate_or_write(self):
        path = Path(self.tmp.name) / "recipe.json"
        path.write_text(json.dumps(self.data))
        commands = [["recipe-template"], ["create", str(path)],
                    ["import-url", "https://example.org/recipe"], ["import-text", str(path)]]
        with patch.object(planner, "get_client", side_effect=AssertionError("no API")):
            for command in commands:
                with self.subTest(command=command), patch("sys.stdout", new_callable=io.StringIO) as output:
                    self.assertEqual(planner.main(command), 0)
                    self.assertIsInstance(json.loads(output.getvalue()), dict)

    def test_confirm_requires_receipt_before_authentication(self):
        with patch.object(planner, "get_client", side_effect=AssertionError("no API")), patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(planner.main(["import-url", "https://example.org/recipe", "--confirm"]), 1)

    def test_confirmed_import_keeps_api_and_source_origins_separate(self):
        with patch.object(planner, "get_client", return_value=self.client) as get_client, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(planner.main(["--url", "https://norish.example", "import-url",
                                           "https://source.example/food", "--confirm", "--receipt", str(self.receipt)]), 0)
        self.assertEqual(get_client.call_args.args[0].url, "https://norish.example")
        self.assertEqual(self.calls, [("POST", "/recipes/import/url", {"url": "https://source.example/food", "forceAI": False})])

    def test_status_command_is_read_only(self):
        with patch.object(planner, "get_client", return_value=self.client), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(planner.main(["status", RID]), 0)
        self.assertEqual(self.calls, [("GET", "/recipes/import/status/" + RID, None)])

    def test_private_import_addresses_are_refused(self):
        for url in ("http://localhost/x", "http://127.0.0.1/x", "http://192.168.1.1/x",
                    "http://[::1]/x", "https://user:pass@example.org/x", "file:///etc/passwd",
                    "http://intranet/x", "http://127.1/x"):
            with self.subTest(url=url), self.assertRaises(planner.PlannerError):
                planner.public_url(url)

    def test_estimates_are_reported_and_need_apply_acknowledgement(self):
        self.client.recipes[RID]["tags"] = [{"name": "planner:nutrition-estimated"}]
        report = planner.evaluate(plan(), self.client)
        self.assertEqual(report["estimatedRecipeIds"], [RID])
        self.assertEqual(report["days"][0]["meals"][0]["nutritionStatus"], "estimated")
        with self.assertRaisesRegex(planner.PlannerError, "ack-estimates"):
            planner.apply_plan(plan(), self.client, self.receipt, TODAY)
        self.assertEqual(self.calls, [])
        client = FakeClient()
        client.recipes[RID]["tags"] = [{"name": "planner:nutrition-estimated"}]
        planner.apply_plan(plan(), client, self.receipt, TODAY, ack_estimates=True)
        self.assertEqual(len(client.writes), 1)


class FdcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.matches = Path(self.tmp.name) / "usda-matches.json"

    def fake(self, detail=None):
        class Fake:
            def get(self, path, params):
                if path.endswith("search"):
                    return {"foods": [{"fdcId": 1, "description": "Milk, whole", "dataType": "Foundation"}]}
                return detail
        return Fake()

    def test_demo_key_is_refused(self):
        for key in ("DEMO_KEY", "   "):
            with self.subTest(key=key), self.assertRaisesRegex(planner.PlannerError, "api.data.gov"):
                planner.Fdc(key)

    def record(self, values, portions=True):
        return planner.fdc_food(self.fake({"fdcId": 1, "description": "Milk, whole", "dataType": "Survey (FNDDS)",
            "foodPortions": [{"sequenceNumber": 4, "gramWeight": 2.5, "measureUnit": {"name": "undetermined"}}]
                             if portions else [],
            "foodNutrients": [{"amount": v, "nutrient": {"id": planner.FDC_NUTRIENT_IDS[m]}}
                              for m, v in values.items()]}), 1)

    def test_amounts_are_already_per_100g_for_every_data_type(self):
        # Real USDA shapes: Foundation swiss cheese and Survey whole milk.
        self.assertEqual(self.record({"calories": 393, "protein": 27, "fat": 31, "carbs": 1.44})["per100g"],
                         {"calories": 393.0, "protein": 27.0, "fat": 31.0, "carbs": 1.44})
        result = self.record({"calories": 61, "protein": 3.27, "fat": 3.2, "carbs": 4.63})
        self.assertEqual(result["portionBasis"], "per-100g")
        self.assertEqual(result["portions"][0]["gramWeight"], 2.5)
        self.assertEqual(result["missingNutrients"], [])

    def test_partial_usda_macros_are_reported(self):
        result = self.record({"calories": 61, "protein": None, "fat": "n/a", "carbs": -1})
        self.assertEqual(result["per100g"], {"calories": 61.0})
        self.assertEqual(result["missingNutrients"], ["carbs", "fat", "protein"])

    def test_record_without_any_macro_values(self):
        result = planner.fdc_food(self.fake({"fdcId": 1, "foodNutrients": []}), 1)
        self.assertIsNone(result["per100g"])
        self.assertEqual(result["missingNutrients"], sorted(planner.MACROS))

    def latte(self, matches):
        return planner.fdc_calc({"servings": 1, "recipeIngredients": [
            {"ingredientName": "whole milk", "amount": 180, "unit": "g"},
            {"ingredientName": "maple syrup", "amount": 15, "unit": "g"},
            {"ingredientName": "espresso", "amount": 2, "unit": "shot"}],
        }, matches, lambda fid: self.fail("no USDA call expected"))

    def test_calc_uses_cached_matches_without_usda_access(self):
        report = self.latte({"whole milk": {"per100g": {"calories": 64, "fat": 3.4, "carbs": 4.8, "protein": 3.4}},
                             "maple syrup": {"per100g": {"calories": 260, "fat": 0, "carbs": 67, "protein": 0}}})
        self.assertEqual(report["perServing"], {"calories": 154.2, "fat": 6.12, "carbs": 18.69, "protein": 6.12})
        self.assertFalse(report["complete"])
        self.assertEqual(report["unmatchedIngredients"], ["espresso"])
        self.assertEqual(report["unquantifiedIngredients"], [])

    def test_matched_but_nonconvertible_unit(self):
        report = self.latte({"whole milk": {"per100g": {"calories": 64, "fat": 3.4, "carbs": 4.8, "protein": 3.4}},
                             "maple syrup": {"per100g": {"calories": 260, "fat": 0, "carbs": 67, "protein": 0}},
                             "espresso": {"per100g": {"calories": 4, "fat": 0, "carbs": 1, "protein": 0}}})
        self.assertFalse(report["complete"])
        self.assertEqual(report["unmatchedIngredients"], [])
        self.assertEqual(report["unquantifiedIngredients"][0]["name"], "espresso")
        self.assertEqual(report["perServing"]["calories"], 154.2)

    def test_volume_density_and_alternate_input_shape(self):
        report = planner.fdc_calc({"servings": 2, "ingredients": [
            {"name": "coffee", "amount": 500, "unit": "ml"}]},
            {"coffee": {"per100g": {"calories": 2, "fat": 0, "carbs": 0, "protein": 0}, "densityGPerMl": 1}},
            lambda fid: self.fail("no USDA call expected"))
        self.assertEqual(report["perServing"]["calories"], 5.0)

    def test_record_missing_one_macro_is_partial_not_complete(self):
        # Mirrors USDA Foundation tomato paste: fat and protein present, calories absent.
        report = self.latte({"whole milk": {"per100g": {"calories": 64, "fat": 3.4, "carbs": 4.8, "protein": 3.4}},
                             "maple syrup": {"per100g": {"calories": 260, "fat": 0, "carbs": 67, "protein": 0}},
                             "espresso": {"per100g": {"fat": 0.18, "carbs": 1.67, "protein": 0.12}, "densityGPerMl": 1.0}})
        self.assertFalse(report["complete"])
        self.assertEqual(report["partialIngredients"], [{"name": "espresso", "missingMacros": ["calories"]}])
        self.assertEqual(report["perServing"]["calories"], 154.2)

    def test_incomplete_report_is_not_presented_as_zero(self):
        report = self.latte({})
        self.assertEqual(report["perServing"], dict.fromkeys(planner.MACROS, 0.0))
        self.assertFalse(report["complete"])
        self.assertEqual(len(report["unmatchedIngredients"]), 3)
        self.assertEqual(report["unquantifiedIngredients"], [])

    def test_match_store_is_private_and_merges(self):
        def add(name, fdc_id, per100g):
            with patch.object(planner, "get_fdc", side_effect=AssertionError("no USDA needed")), patch("sys.stdout", new_callable=io.StringIO):
                return planner.main(["fdc-add-match", name, fdc_id, "--matches", str(self.matches),
                                     "--per-100g", per100g])
        self.assertEqual(add("Whole Milk", "1", '{"calories":64,"fat":3.4,"carbs":4.8,"protein":3.4}'), 0)
        self.assertEqual(self.matches.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(planner.load_matches(self.matches)), ["whole milk"])
        self.assertEqual(add("Milk", "2", '{"calories":1,"fat":0,"carbs":0,"protein":0}'), 0)
        self.assertEqual(len(planner.load_matches(self.matches)), 2)

    def test_bad_per100g_and_missing_usda_key_fail_cleanly(self):
        def bad(per100g):
            with patch.object(planner, "get_fdc", side_effect=AssertionError("no USDA needed")), patch("sys.stderr", new_callable=io.StringIO):
                return planner.main(["fdc-add-match", "Milk", "1", "--matches", str(self.matches),
                                     "--per-100g", per100g])
        self.assertEqual(bad("not json"), 1)
        self.assertEqual(bad('{"calories":-1}'), 1)
        self.assertFalse(self.matches.exists())
        with patch.object(planner, "get_fdc", side_effect=planner.PlannerError("Create a free key")), patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(planner.main(["fdc-search", "milk"]), 1)


if __name__ == "__main__":
    unittest.main()
