from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .config import DEFAULT_API_VERSION, Config, load_config, save_config
from .shopify import ShopifyAPIError, ShopifyClient
from .search import query_from_parts

console = Console()
app = typer.Typer(help="CLI to explore Shopify metaobjects.")
config_app = typer.Typer(
    name="config", help="Persist store credentials for quicker use."
)
meta_app = typer.Typer(
    name="metaobjects", help="Browse metaobject definitions and entries."
)
app.add_typer(config_app, name="config")
app.add_typer(meta_app, name="metaobjects")


def resolve_config(
    store: Optional[str], token: Optional[str], api_version: Optional[str]
) -> Config:
    current = load_config()
    if store and token:
        return Config(
            store_domain=store,
            access_token=token,
            api_version=api_version or DEFAULT_API_VERSION,
        )
    if current:
        return Config(
            store_domain=store or current.store_domain,
            access_token=token or current.access_token,
            api_version=api_version or current.api_version,
        )
    console.print(
        Panel(
            "[bold red]No credentials found.[/]\n"
            "Run `shopmetactl config set --store your-store --token xxx` first.",
            title="Setup needed",
        )
    )
    raise typer.Exit(code=1)


@config_app.command("set", help="Store store/token/API version under ~/.shopmeta.")
def set_config(
    store: str = typer.Option(..., "--store", help="my-store.myshopify.com"),
    token: str = typer.Option(..., "--token", help="Admin API access token"),
    api_version: str = typer.Option(
        DEFAULT_API_VERSION,
        "--api-version",
        help=f"Shopify Admin API version (default {DEFAULT_API_VERSION})",
    ),
) -> None:
    config = Config(store_domain=store, access_token=token, api_version=api_version)
    path = save_config(config)
    console.print(
        Panel(
            f"[bold green]Stored credentials for[/] {config.sanitized_domain}\n"
            f"[dim]{path}[/]",
            title="Done",
        )
    )


@config_app.command("show", help="Display whichever config source is active.")
def show_config() -> None:
    config = load_config()
    if not config:
        console.print("[yellow]No stored config. Use env vars or `config set`.")  # type: ignore[arg-type]
        raise typer.Exit(code=1)

    table = Table(box=None, show_header=False)
    table.add_row("Store", config.sanitized_domain)
    table.add_row("API version", config.api_version)
    table.add_row("Token", f"{config.access_token[:4]}…{config.access_token[-4:]}")
    console.print(Panel(table, title="Active config"))


@meta_app.command("tree", help="Render a tree view of definitions + sample entries.")
def meta_tree(
    types_limit: int = typer.Option(
        5, "--types", help="How many definitions to fetch."
    ),
    entries_limit: int = typer.Option(5, "--entries", help="Entries per definition."),
    store: Optional[str] = typer.Option(
        None, "--store", help="Override configured store."
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="Override configured token."
    ),
    api_version: Optional[str] = typer.Option(
        None, "--api-version", help="Override API version."
    ),
) -> None:
    config = resolve_config(store, token, api_version)
    client = ShopifyClient(config)

    try:
        with console.status("[bold cyan]Fetching metaobject definitions…"):
            definitions = client.fetch_metaobject_tree(types_limit, entries_limit)
    except ShopifyAPIError as exc:
        show_api_error(exc)
        raise typer.Exit(code=1) from exc

    tree = Tree("[bold cyan]Metaobject definitions[/]")
    if not definitions:
        tree.add(
            "[yellow]No metaobjects found. Head to the Shopify admin to create one."
        )
    else:
        for definition in definitions:
            render_definition(tree, definition, entries_limit)
    console.print(tree)


@meta_app.command("view", help="Show one metaobject definition and its entries.")
def meta_view(
    type_name: str = typer.Argument(..., help="Metaobject type, e.g. namespace.handle"),
    limit: int = typer.Option(10, "--limit", help="How many entries to fetch."),
    store: Optional[str] = typer.Option(
        None, "--store", help="Override configured store."
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="Override configured token."
    ),
    api_version: Optional[str] = typer.Option(
        None, "--api-version", help="Override API version."
    ),
) -> None:
    config = resolve_config(store, token, api_version)
    client = ShopifyClient(config)

    try:
        with console.status(f"[bold cyan]Fetching {type_name}…"):
            definition = client.fetch_metaobject_definition(type_name, limit)
    except ShopifyAPIError as exc:
        show_api_error(exc)
        raise typer.Exit(code=1) from exc

    if not definition:
        console.print(f"[yellow]No definition found for[/] [bold]{type_name}[/]")
        raise typer.Exit(code=1)

    console.print(
        Panel(render_definition_summary(definition), title=definition["name"])
    )
    entries = definition.get("metaobjects", {}).get("nodes", [])
    table = Table(
        "Display name",
        "Handle",
        "Updated",
        "Fields",
        title=f"Entries ({len(entries)} shown)",
        show_lines=True,
    )

    if not entries:
        console.print("[yellow]No metaobjects found for this type.")
        return

    for entry in entries:
        field_text = "\n".join(
            f"[cyan]{f['key']}[/]: {truncate(f['value'])}"
            for f in entry.get("fields", [])
        )
        table.add_row(
            entry.get("displayName") or entry.get("handle"),
            entry.get("handle", "—"),
            entry.get("updatedAt", "—"),
            field_text or "[dim]No fields[/]",
        )

    console.print(table)


@meta_app.command("dump", help="Write definition + entries to JSON for diffing.")
def meta_dump(
    type_name: str = typer.Argument(..., help="Metaobject type to export."),
    limit: int = typer.Option(50, "--limit", help="Max entries to include."),
    output: Path = typer.Option(
        Path("metaobject_dump.json"),
        "--out",
        help="Destination JSON path.",
        dir_okay=False,
    ),
    store: Optional[str] = typer.Option(
        None, "--store", help="Override configured store."
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="Override configured token."
    ),
    api_version: Optional[str] = typer.Option(
        None, "--api-version", help="Override API version."
    ),
) -> None:
    config = resolve_config(store, token, api_version)
    client = ShopifyClient(config)
    try:
        with console.status(f"[bold cyan]Fetching {type_name}…"):
            definition = client.fetch_metaobject_definition(type_name, limit)
    except ShopifyAPIError as exc:
        show_api_error(exc)
        raise typer.Exit(code=1) from exc
    if not definition:
        console.print(f"[yellow]No definition found for[/] [bold]{type_name}[/]")
        raise typer.Exit(code=1)

    payload = {
        "type": type_name,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "definition": {k: v for k, v in definition.items() if k != "metaobjects"},
        "entries": definition.get("metaobjects", {}).get("nodes", []),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    console.print(
        Panel(
            f"Wrote {len(payload['entries'])} entries → {output}", title="Dump complete"
        )
    )


@meta_app.command("watch", help="Poll a definition and highlight changed entries.")
def meta_watch(
    type_name: str = typer.Argument(..., help="Metaobject type to monitor."),
    limit: int = typer.Option(20, "--limit", help="Max entries per refresh."),
    interval: float = typer.Option(
        3.0, "--interval", help="Seconds between refreshes."
    ),
    store: Optional[str] = typer.Option(
        None, "--store", help="Override configured store."
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="Override configured token."
    ),
    api_version: Optional[str] = typer.Option(
        None, "--api-version", help="Override API version."
    ),
) -> None:
    config = resolve_config(store, token, api_version)
    client = ShopifyClient(config)
    last_signature: dict[str, str] = {}
    try:
        with Live(console=console, refresh_per_second=8) as live:
            while True:
                try:
                    definition = client.fetch_metaobject_definition(type_name, limit)
                except ShopifyAPIError as exc:
                    show_api_error(exc)
                    raise typer.Exit(code=1) from exc
                if not definition:
                    console.print(
                        f"[yellow]No definition found for[/] [bold]{type_name}[/]"
                    )
                    raise typer.Exit(code=1)
                table, signature = render_watch_table(definition, last_signature)
                last_signature = signature
                live.update(table)
                time.sleep(
                    max(0.5, interval)
                )  # Textual redraw flickers if we hammer faster than 2 Hz
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped watch loop[/]")


@meta_app.command("search", help="Launch the interactive Textual search UI.")
def meta_search(
    query: Optional[str] = typer.Option(
        None, "--query", "-q", help="Initial query string."
    ),
    namespace: Optional[str] = typer.Option(
        None, "--namespace", "-n", help="Namespace portion of metaobject type."
    ),
    key: Optional[str] = typer.Option(
        None, "--key", "-k", help="Key/handle portion of metaobject type."
    ),
    limit: int = typer.Option(20, "--limit", help="Max results to keep in memory."),
    store: Optional[str] = typer.Option(
        None, "--store", help="Override configured store."
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="Override configured token."
    ),
    api_version: Optional[str] = typer.Option(
        None, "--api-version", help="Override API version."
    ),
) -> None:
    try:
        from .tui import MetaobjectSearchApp
    except ImportError as exc:  # pragma: no cover - import guard
        console.print(
            Panel(
                "[bold red]Textual is not installed.[/]\n"
                "Reinstall the package with `pip install textual` or `pip install -e .`.",
                title="Missing dependency",
            )
        )
        raise typer.Exit(code=1) from exc

    config = resolve_config(store, token, api_version)
    client = ShopifyClient(config)
    initial = query or query_from_parts(namespace, key) or ""
    MetaobjectSearchApp(client, limit=limit, initial_query=initial).run()


def render_definition(tree: Tree, definition: dict, entries_limit: int) -> None:
    label = Text(
        definition.get("name") or definition.get("type") or "Untitled",
        style="bold white",
    )
    label.append(f"  ({definition.get('type', 'unknown')})", style="dim")
    def_node = tree.add(label)

    fields = definition.get("fieldDefinitions", [])
    if fields:
        fields_node = def_node.add(f"[green]{len(fields)} field definitions[/]")
        for field in fields:
            field_label = (
                f"[cyan]{field.get('key')}[/] "
                f"[dim]{field.get('type', {}).get('name', '').upper()}[/]"
            )
            if field.get("description"):
                field_label += f"\n[dim]{field['description']}"
            fields_node.add(field_label)
    else:
        def_node.add("[dim]No field definitions[/]")

    entries = definition.get("metaobjects", {}).get("nodes", [])
    entries_node = def_node.add(
        f"[magenta]{len(entries)} entry sample[/] (max {entries_limit})"
    )
    if not entries:
        entries_node.add("[dim]No entries yet[/]")
        return

    for entry in entries:
        entry_label = Text(
            entry.get("displayName") or entry.get("handle") or "Untitled", style="bold"
        )
        entry_label.append(f" · {entry.get('handle', '—')}", style="dim")
        entry_node = entries_node.add(entry_label)
        for field in entry.get("fields", []):
            entry_node.add(f"[cyan]{field['key']}[/]: {truncate(field['value'])}")


def render_definition_summary(definition: dict) -> Align:
    table = Table.grid(padding=1)
    table.add_row("Type", definition.get("type", "—"))
    table.add_row("Fields", str(len(definition.get("fieldDefinitions", []))))
    if (pi := definition.get("metaobjects", {}).get("pageInfo")) and pi.get(
        "hasNextPage"
    ):
        table.add_row("More entries", "Available (use --limit to load more)")
    return Align.center(table)


def render_watch_table(
    definition: dict, last_signature: dict[str, str]
) -> tuple[Table, dict[str, str]]:
    table = Table(
        "Display name",
        "Handle",
        "Updated",
        "Fields",
        title=f"{definition.get('name')} · {datetime.now().strftime('%H:%M:%S')}",
        show_lines=True,
    )
    signature: dict[str, str] = {}
    entries = definition.get("metaobjects", {}).get("nodes", [])
    for entry in entries:
        entry_id = entry.get("id", "")
        sig = f"{entry.get('updatedAt','')}|{len(entry.get('fields', []))}"
        signature[entry_id] = sig
        style = "bold yellow" if last_signature.get(entry_id) != sig else ""
        field_text = "\n".join(
            f"[cyan]{f['key']}[/]: {truncate(f['value'])}"
            for f in entry.get("fields", [])
        )
        table.add_row(
            entry.get("displayName") or entry.get("handle") or entry_id,
            entry.get("handle", "—"),
            entry.get("updatedAt", "—"),
            field_text or "[dim]No fields[/]",
            style=style,
        )
    if not entries:
        table.add_row("[dim]No entries[/]", "", "", "")
    return table, signature


def truncate(value: Optional[str], limit: int = 60) -> str:
    if not value:
        return "—"
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def show_api_error(exc: ShopifyAPIError) -> None:
    console.print(
        Panel(
            Text(str(exc), style="bold red"),
            title="Shopify API error",
            subtitle="Double-check your token, store, and API version.",
        )
    )


if __name__ == "__main__":
    app()
