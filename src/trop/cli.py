"""Typer CLI entry point: ``trop run``, ``trop eval``, ``trop classes``, ``trop new-class``."""

from __future__ import annotations

import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.table import Table

from trop import __version__
from trop.orchestrator import process_case
from trop.registry.loader import (
    clear_registry_cache,
    default_classes_dir,
    load_classes_report,
)
from trop.settings import _repo_root, clear_settings_cache, get_settings

_CLASS_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

app = typer.Typer(
    name="trop",
    help="TROP — HackNation Odwołania2json (PDF → JSON).",
    add_completion=False,
    no_args_is_help=True,
)
classes_app = typer.Typer(help="Document class registry commands.")
app.add_typer(classes_app, name="classes")
console = Console(stderr=True)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
        force=True,
    )


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"trop {__version__}")
        raise typer.Exit(0)


def _ensure_repo_on_path() -> None:
    """Allow ``import eval`` from repo-root eval package."""
    root = str(_repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """TROP CLI."""


@app.command("run")
def run(
    input: Path = typer.Option(  # noqa: A001 — CLI flag name matches product contract
        ...,
        "--input",
        "-i",
        help="Input directory containing PDF files (searched recursively).",
        exists=False,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output directory for mirrored same-stem JSON files.",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    evidence: Optional[Path] = typer.Option(
        None,
        "--evidence",
        "-e",
        help="Optional evidence/debug dump directory.",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        "-w",
        help="Parallel workers (default: max(1, cpu//2) from config).",
        min=1,
    ),
) -> None:
    """Process every PDF under INPUT into OUTPUT (non-interactive).

    Per-file errors / OOC write ``{}`` and continue. Exit 0 when INPUT exists.
    """
    clear_settings_cache()
    clear_registry_cache()
    settings = get_settings()
    _configure_logging(settings.log_level)

    if not input.is_dir():
        console.print(f"[red]Input directory does not exist:[/red] {input}")
        raise typer.Exit(code=2)

    # Evidence only when CLI `--evidence` or settings/env explicitly set a path.
    # Default config leaves evidence_dir null (sidecars off).
    evidence_dir = evidence if evidence is not None else settings.evidence_dir
    result = process_case(
        input,
        output,
        evidence_dir=evidence_dir,
        workers=workers,
        settings=settings,
    )
    console.print(
        f"[green]OK[/green] {result.succeeded}/{result.total} "
        f"(failed={result.failed}) classes={result.classified} → {result.output_dir}"
    )
    raise typer.Exit(code=0)


@app.command("eval")
def eval_cmd(
    pred: Path = typer.Option(
        ...,
        "--pred",
        help="Directory of predicted JSON files (mirrored tree).",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    gold: Path = typer.Option(
        ...,
        "--gold",
        help="Directory of gold JSON files.",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    map: Optional[Path] = typer.Option(  # noqa: A001
        None,
        "--map",
        help="Optional gold_map.yaml (default: eval/gold_map.yaml).",
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    report: Optional[Path] = typer.Option(
        None,
        "--report",
        help=(
            "Write report to this path. Suffix selects format: "
            ".json (default), .md (markdown table), .csv. "
            "Suggested: eval/reports/dev.md"
        ),
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
) -> None:
    """Score predictions against gold (micro-F1). Hold-out: przyklad_46–60."""
    _ensure_repo_on_path()
    from eval.score import evaluate, format_report, write_report

    if not pred.is_dir():
        console.print(f"[red]Pred directory missing:[/red] {pred}")
        raise typer.Exit(code=2)
    if not gold.is_dir():
        console.print(f"[red]Gold directory missing:[/red] {gold}")
        raise typer.Exit(code=2)

    map_path = map
    if map_path is None:
        default_map = _repo_root() / "eval" / "gold_map.yaml"
        if default_map.is_file():
            map_path = default_map

    result = evaluate(pred, gold, map_path=map_path)
    console.print(format_report(result))
    if report is not None:
        out = write_report(result, report)
        console.print(f"Report → {out}")
    raise typer.Exit(code=0)


@classes_app.command("list")
def classes_list() -> None:
    """List registered document classes from ``classes/*/class.yaml``.

    Exits 1 when no class loads or any class config has problems (invalid
    regex, unknown extractor type / normalizer / block).
    """
    clear_registry_cache()
    specs, problems = load_classes_report()
    table = Table(title=f"Classes ({default_classes_dir()})")
    table.add_column("id")
    table.add_column("label")
    table.add_column("threshold")
    table.add_column("margin")
    table.add_column("keywords")
    table.add_column("fields")
    for spec in specs:
        table.add_row(
            spec.id,
            spec.label,
            str(spec.detect.threshold),
            str(spec.detect.margin),
            str(len(spec.detect.keywords)),
            str(len(spec.fields) + len(spec.lists)),
        )
    console.print(table)
    for problem in problems:
        # escape(): paths like fields[a.b] would otherwise be eaten as markup.
        console.print(
            f"[red]Config problem:[/red] {escape(problem)}", highlight=False, soft_wrap=True
        )
    if not specs:
        console.print("[yellow]No classes found.[/yellow]")
        raise typer.Exit(code=1)
    raise typer.Exit(code=1 if problems else 0)


@app.command("new-class")
def new_class(
    class_id: str = typer.Argument(
        ...,
        metavar="ID",
        help="New class folder id (lowercase letters, digits, underscore).",
    ),
    label: Optional[str] = typer.Option(
        None,
        "--label",
        "-l",
        help="Human-readable label (default: derived from ID).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite destination if it already exists.",
    ),
) -> None:
    """Copy ``classes/_template`` to ``classes/<ID>`` and rewrite placeholders."""
    if not _CLASS_ID_RE.match(class_id):
        console.print(
            "[red]Invalid class id[/red]: use lowercase [a-z][a-z0-9_]{1,63} "
            f"(got {class_id!r})"
        )
        raise typer.Exit(code=2)

    classes_root = default_classes_dir()
    template = classes_root / "_template"
    dest = classes_root / class_id
    if not template.is_dir() or not (template / "class.yaml").is_file():
        console.print(f"[red]Template missing:[/red] {template}")
        raise typer.Exit(code=2)
    if dest.exists() and not force:
        console.print(f"[red]Already exists:[/red] {dest} (pass --force to overwrite)")
        raise typer.Exit(code=2)

    display = label or class_id.replace("_", " ").strip().title()
    if dest.exists() and force:
        shutil.rmtree(dest)
    shutil.copytree(template, dest)

    class_yaml = dest / "class.yaml"
    text = class_yaml.read_text(encoding="utf-8")
    text = text.replace("__CLASS_ID__", class_id).replace("__CLASS_LABEL__", display)
    class_yaml.write_text(text, encoding="utf-8")

    schema_path = dest / "schema.json"
    if schema_path.is_file():
        schema_text = schema_path.read_text(encoding="utf-8")
        schema_path.write_text(
            schema_text.replace("__CLASS_ID__", class_id),
            encoding="utf-8",
        )

    clear_registry_cache()
    console.print(f"[green]Created[/green] {dest}")
    console.print("Edit detect keywords + extractors, then: trop classes list")
    raise typer.Exit(code=0)


def main() -> None:
    """Console-script / ``python -m trop`` entry."""
    app()


if __name__ == "__main__":
    main()
