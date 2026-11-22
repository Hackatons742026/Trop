# Adding a document class

TROP discovers classes from disk: any `classes/<id>/class.yaml` is loaded at
runtime. **No Python import or registry edit is required.** Folders whose names
start with `_` (for example `_template`, `_demo_przystapienie`) are ignored.

## Steps

1. **Scaffold from the template**

   ```bash
   trop new-class my_class
   ```

   This copies `classes/_template/` → `classes/my_class/` and rewrites `id` /
   `label` / schema `$id`.

2. **Edit detection keywords** in `classes/my_class/class.yaml`

   - Detection is **content-only** (never the PDF filename).
   - Tune `detect.threshold` and `detect.margin`.
   - Prefer specific Polish legal phrases with sensible weights.

3. **Define extractors**

   - `blocks` — optional text windows (`start` / `end` regex).
   - `fields` — dotted paths + `regex` / `label` / `const` / `derived` extractors.
   - `lists` — array-shaped sections (`mode: single` or `multi_from_regex`).
   - Use `normalize:` hooks already in the pipeline (`date_pl`, `krs_pad10`, …).

4. **Align `schema.json`**

   - Mirror the official competition JSON shape for that document type.
   - Missing leaves are **`null`** (allow `"type": ["string", "null"]` etc.).
   - `additionalProperties: false` when the contract is strict.
   - The extractor builds a null-filled skeleton from this schema; scored JSON
     is validated with `jsonschema` before write (invalid → `{}`).

5. **Optional dicts**

   - Put lookup YAML under `classes/my_class/dicts/*.yaml` if you need id→label maps.

6. **Verify discovery**

   ```bash
   trop classes list
   pytest tests/test_new_class.py -q
   ```

   Default official classes: `odwolanie`, `pelnomocnictwo`, `przelew`.

7. **Smoke on a PDF**

   ```bash
   trop run --input input --output output --workers 2
   ```

   Out-of-class / look-alike / hard failure → exactly `{}` (same stem as the PDF).

## Demo example (not registered)

`classes/_demo_przystapienie/` is a minimal **docs-only** example (folder name
starts with `_`, so `trop classes list` / Docker do not load it). Copy it to a
non-`_` folder when experimenting with config-only classes.

## Docker note

Compose mounts `./classes` into `/opt/solution/classes`, so new folders appear
inside the container without rebuilding the image.
