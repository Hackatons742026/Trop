#!/usr/bin/env python3
"""Import HackNation training PDFs + gold JSON into gitignored ``data/train``.

Source: https://github.com/Urzad-Zamowien-Publicznych/hacknation-2026
  - ``dane/``            → PDFs (+ co-located gold JSON)
  - ``oczekiwane-json/`` → official schema examples / dict

Layout written (gitignored via ``data/``):

  data/train/
    input/          # PDFs only (mirrors dane/ tree)
    gold/           # JSON gold (same relative stems; {}.json for negatives without gold)
    oczekiwane-json/
    raw/            # optional full clone/copy of source folders

Usage:
  python tools/import_gold.py
  python tools/import_gold.py --repo-url https://github.com/Urzad-Zamowien-Publicznych/hacknation-2026
  python tools/import_gold.py --from-dir path/to/local/hacknation-2026

Does NOT commit data. Network/clone failures exit non-zero with a clear message;
synthetic fixtures under tests/fixtures/ remain available offline.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_REPO = "https://github.com/Urzad-Zamowien-Publicznych/hacknation-2026"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "train"


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def obtain_source(repo_url: str, from_dir: Path | None, work: Path) -> Path:
    if from_dir is not None:
        src = Path(from_dir)
        if not src.is_dir():
            raise FileNotFoundError(f"--from-dir not a directory: {src}")
        return src

    clone_dir = work / "hacknation-2026"
    try:
        _run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                repo_url,
                str(clone_dir),
            ]
        )
        _run(
            ["git", "sparse-checkout", "set", "dane", "oczekiwane-json"],
            cwd=clone_dir,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # Fallback: shallow full clone
        if clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)
        try:
            _run(["git", "clone", "--depth", "1", repo_url, str(clone_dir)])
        except (subprocess.CalledProcessError, FileNotFoundError) as exc2:
            raise RuntimeError(
                "Could not clone hacknation-2026. "
                "Pass --from-dir to a local checkout, or use tests/fixtures/ offline."
            ) from exc2
        _ = exc
    return clone_dir


def copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def split_dane(dane: Path, input_dir: Path, gold_dir: Path) -> tuple[int, int]:
    """Copy PDFs → input/, JSON → gold/. Invent ``{}`` gold for PDFs lacking JSON."""
    pdf_count = 0
    gold_count = 0
    if not dane.is_dir():
        raise FileNotFoundError(f"dane/ missing under source: {dane}")

    for path in dane.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(dane)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            dest = input_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            pdf_count += 1
            gold_candidate = path.with_suffix(".json")
            # Special: potwierdzenie_przelewu.pdf → przelew.json in same folder
            alt = path.parent / "przelew.json"
            gold_rel = rel.with_suffix(".json")
            gold_dest = gold_dir / gold_rel
            gold_dest.parent.mkdir(parents=True, exist_ok=True)
            if gold_candidate.is_file():
                shutil.copy2(gold_candidate, gold_dest)
                gold_count += 1
            elif path.stem.lower().startswith("potwierdzenie") and alt.is_file():
                shutil.copy2(alt, gold_dest)
                gold_count += 1
            elif not gold_dest.exists():
                # Negatives / look-alikes without gold → expect {}
                gold_dest.write_text("{}\n", encoding="utf-8")
                gold_count += 1
        elif suffix == ".json":
            # Also keep canonical gold stems (odwolanie.json etc.) for eval by stem
            dest = gold_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(path, dest)
                gold_count += 1
    return pdf_count, gold_count


def write_manifest(out: Path, pdf_count: int, gold_count: int, source: str) -> None:
    manifest = {
        "source": source,
        "pdf_count": pdf_count,
        "gold_count": gold_count,
        "holdout": "przyklad_46 .. przyklad_60",
        "layout": {
            "input": "data/train/input",
            "gold": "data/train/gold",
            "oczekiwane-json": "data/train/oczekiwane-json",
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", default=DEFAULT_REPO)
    parser.add_argument("--from-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Also keep a raw copy of dane/ + oczekiwane-json/ under out/raw/",
    )
    args = parser.parse_args(argv)

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    input_dir = out / "input"
    gold_dir = out / "gold"
    schemas_dir = out / "oczekiwane-json"

    with tempfile.TemporaryDirectory(prefix="trop-gold-") as tmp:
        work = Path(tmp)
        try:
            source = obtain_source(args.repo_url, args.from_dir, work)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        dane = source / "dane"
        oczekiwane = source / "oczekiwane-json"
        if not dane.is_dir():
            print(f"ERROR: dane/ not found under {source}", file=sys.stderr)
            return 2

        if input_dir.exists():
            shutil.rmtree(input_dir)
        if gold_dir.exists():
            shutil.rmtree(gold_dir)
        input_dir.mkdir(parents=True)
        gold_dir.mkdir(parents=True)

        pdf_count, gold_count = split_dane(dane, input_dir, gold_dir)

        if oczekiwane.is_dir():
            copy_tree(oczekiwane, schemas_dir)
        else:
            print("WARN: oczekiwane-json/ missing — skipped", file=sys.stderr)

        if args.keep_raw:
            raw = out / "raw"
            raw.mkdir(parents=True, exist_ok=True)
            copy_tree(dane, raw / "dane")
            if oczekiwane.is_dir():
                copy_tree(oczekiwane, raw / "oczekiwane-json")

        write_manifest(out, pdf_count, gold_count, str(args.from_dir or args.repo_url))
        print(f"Imported {pdf_count} PDFs, {gold_count} gold JSON → {out}")
        print("Hold-out cases: przyklad_46–przyklad_60 (flagged by trop eval --report)")
        print("Remember: data/ is gitignored — do not commit training files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
