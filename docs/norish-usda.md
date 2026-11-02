# USDA-backed macro calculation

`norish-planner` can match recipe ingredients to USDA FoodData Central records
and calculate calorie/fat/carb/protein totals from gram quantities. This is
separate from [recipe writes](norish-recipe-writes.md); it produces the numbers
you then supply to `create` with an explicit nutrition status.

## USDA key

Create a free key at **https://api.data.gov/signup/** and store it privately:

```sh
install -d -m 0700 ~/.config/norish-planner
(umask 077; read -rsp 'USDA API key: ' key; printf '\n';
 printf '%s\n' "$key" > ~/.config/norish-planner/usda-key; unset key)
```

`USDA_API_KEY` is also supported. `--usda-key-file` selects another private file.
**Do not use `DEMO_KEY`:** it returns records with nutrient values stripped, which
would silently produce empty results. The CLI rejects it explicitly.

## Commands

```sh
# Find candidate foods. GENERAL prefers USDA's own foods over branded products.
norish-planner fdc-search 'whole milk' --type GENERAL
norish-planner fdc-search 'maple syrup'

# Inspect one record and see whether macros can be converted to per-100 g.
norish-planner fdc-food 400626

# Record a reviewed match; the tool fetches the record and stores its
# per-100 g macros. Names are stored lowercased.
norish-planner fdc-add-match 'whole milk' 746782
norish-planner fdc-add-match 'maple syrup' 169661

# Volume ingredients need a density (g/ml) for ml/cup/tbsp/shot conversions.
norish-planner fdc-add-match 'espresso' 171891 --density 1.0

# Calculate from a recipe file. Read-only; no Norish or USDA write occurs.
norish-planner fdc-calc new-recipe.json
```

Matches live in `~/.config/norish-planner/usda-matches.json` (mode 0600, shared
by `fdc-add-match`, `fdc-matches` and `fdc-calc`). They are **your reviewed
decisions**, not automatic selections: the tool never picks a USDA record for you.

## How the calculation works

USDA's `/fdc/v1/food/{id}` response carries each nutrient as
`foodNutrients[].amount`, **already normalised to per-100 g** for Foundation,
SR Legacy, Survey (FNDDS) and Branded records alike. Verified against live
records: Foundation swiss cheese reports 393 kcal and 27 g protein, Survey
whole milk 61 kcal and 3.27 g protein—both recognisable per-100 g figures.

The tool therefore performs **no portion conversion**. `foodPortions` is reported
for context only, so you can see what USDA's own serving descriptions look like
without the calculation depending on them.

Macro nutrient IDs are fixed: Energy 1008, Protein 1003, Total lipid (fat) 1004,
Carbohydrate (by difference) 1005. Ingredient gram quantities are multiplied by
the per-100 g values and the total divided by the recipe's servings.

When a USDA record lacks one of the four macros, `fdc-food` lists it under
`missingNutrients` rather than reporting zero. Record label-checked values yourself
with `fdc-add-match --per-100g '{"calories":250,"fat":3,"carbs":12,"protein":9}'`.

Ingredient units convert to grams when recognised (`g`, `kg`, `oz`, `lb`, `ml`,
`cup`, `tbsp`, `tsp`). Volume units are multiplied by a `--density` you supply;
**`shot` is taken as 30 ml**, so a double shot is 60 ml—check that against how you
actually pull espresso. Unrecognised units such as “clove”, and ingredients
without an amount, are listed under `unquantifiedIngredients` and **excluded from
the totals**.

## Interpreting the report

`fdc-calc` returns `perServing`, `complete`, `unmatchedIngredients`,
`unquantifiedIngredients` and `sources`.

- `complete: false` means the totals are **incomplete, not zero**. Add the
  missing matches/quantities or accept the shortfall explicitly.
- `sources` lists the USDA record used for each line, so you can audit the choice.
- USDA values describe the matched food as recorded—**not your preparation**.
  Cooked versus dry rice, drained versus canned, and reduction all differ.
- A branded record reflects that product; a general record may not match the
  brand you actually buy.

## Feeding the result into Norish

Put the calculated values into the recipe file's `nutrition.perServing`, then
choose the status honestly:

- **`estimated`** — the normal case: USDA records were matched by you, but
  preparation/portion assumptions remain.
- **`verified`** — only when you have checked the figures against a trustworthy
  source such as the actual product label.

Set `nutrition.source` to something specific and durable, for example:

> USDA FoodData Central fdcIds 400626 (whole milk), 595770 (maple syrup);
> espresso excluded as an unquantified “shot” unit; preparation assumptions
> reviewed by me on 2026-11-01.

Then preview and create as described in the recipe-write runbook. The tool records
this provenance in the recipe notes and tags it `planner:nutrition-estimated`
or `planner:nutrition-verified`.

## Writing the result back: `set-nutrition`

`fdc-calc` is read-only. To replace an existing recipe's stored macros:

```sh
norish-planner fdc-calc recipe.json > report.json
norish-planner set-nutrition <recipeId> --report report.json \
  --receipt ~/.local/state/norish-planner/nutrition/<name>.json --confirm
```

The command requires `--confirm` and a `--receipt`, and it:

- refuses an incomplete report unless you pass `--ack-incomplete`;
- sends a **version-checked** tRPC update omitting `images`, so photos survive;
- **reads the recipe back** and fails if the values did not land — Norish logs a
  stale update yet still returns `success: true`, so the response alone proves nothing;
- replaces any existing `[norish-planner nutrition]` block rather than stacking
  duplicates, and swaps the `planner:nutrition-*` tag;
- records the previous values in the receipt, which blocks re-submission.

The note now names the USDA records and the gram quantities actually used, so the
number can be audited later without the match store.

## Applied to the existing library

All four recipes carry USDA-derived macros with provenance notes and
`planner:nutrition-estimated` tags. The website-reported values they replaced are
kept in the receipts under `~/.local/state/norish-planner/nutrition/`:

| Recipe | Was | Now |
|---|---|---|
| Maple Latte | 155 / 6 / 20 / 6 (hand estimate) | 152 / 5.88 / 19.39 / 5.96 |
| Baked Cod | 319 / 19.80 / 9.60 / 25.80 | 318 / 19.55 / 9.36 / 25.76 |
| Tortellini Soup | 256 / 8.60 / 32.80 / 12.50 | 469 / 25.57 / 33.86 / 27.67 |
| Roasted Broccoli | 66 / *null* / 13.90 / 5.10 | 307 / 28.15 / 11.61 / 4.85 |

The soup is written with `--ack-incomplete`: USDA's Foundation tomato paste record
has no calorie value, so its ~27 kcal contribution is absent from that total.

## Scope

This currently covers the **four macros only**. Fibre, sodium, sugars and
vitamins/minerals are not calculated here; that remains the planned work around
Norish's upcoming extended-nutrition support.

## Verification

Offline tests cover USDA key rejection, per-100 g handling for every data type,
null values treated as unknown, unit/density conversion, incomplete reporting,
private match-store writes, and `set-nutrition` (approval gate, incomplete-report
gate, notes/tag rewriting, image preservation, read-back detection of stale writes,
receipt replay).

Live USDA requests have been made with a real key, confirming the per-100 g
behaviour above and the records used for the Maple Latte.

## Maple Latte: worked example

The three ingredients were matched to USDA records and the recipe updated in place
via the tRPC `recipes.update` mutation (version-checked, `images` omitted so the
photo was preserved):

| Ingredient | USDA record | per 100 g |
| --- | --- | --- |
| whole milk | 746782 Foundation | 60 kcal, 3.27 p, 3.2 f, 4.63 c |
| maple syrup | 169661 SR Legacy | 260 kcal, 0.04 p, 0.06 f, 67.04 c |
| espresso | 171891 SR Legacy | 9 kcal, 0.12 p, 0.18 f, 1.67 c |

Result per serving: **152 kcal, 5.88 g fat, 19.39 g carbs, 5.96 g protein**,
reported as `complete: true` with no unmatched or unquantified ingredients.

These replaced a rougher hand estimate (155/6/20/6). The gap is small, which is
what you want from a hand estimate for a simple drink—the point is that the stored
figures now trace to named USDA records instead of guesswork.

Note that `recipes.update` is **tRPC-only**: the public REST API exposes no recipe
update endpoint. The planner's `create` path covers new recipes; changing an
existing recipe's nutrition is done by sending a partial update with the current
`version` and omitting `images`.
