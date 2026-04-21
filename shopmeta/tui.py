from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static, Tree

from .shopify import ShopifyClient, ShopifyAPIError
from .search import parse_search_query


class SearchFailed(Message):
    # bubbles Shopify errors from worker thread back to the UI loop

    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__()


class MetaobjectSearchApp(App[None]):
    CSS = """
    Screen {
        align: center middle;
        padding: 1 2;
        background: #05060a;
        color: #e8e8ff;
    }
    #chrome {
        height: 1fr;
        width: 100%;
        border: tall #22263f;
    }
    #query {
        margin: 1;
        padding: 0 1;
        border: round #5f68ff;
        background: #0c0f1b;
    }
    #body {
        height: 1fr;
        margin: 0 1 1 1;
    }
    ListView {
        width: 40%;
        border: round #373f7a;
        padding: 0 0 1 0;
        background: #090b15;
    }
    ListItem {
        padding: 1 1;
    }
    ListItem.--highlight {
        background: #1b1f33;
    }
    Tree {
        background: #090b15;
        border: round #373f7a;
        width: 60%;
        margin-left: 1;
    }
    #status {
        margin: 0 1 1 1;
        height: 3;
    }
    """

    BINDINGS = [
        ("q", "app.quit", "Quit"),
        ("/", "focus_search", "Search"),
        ("r", "refresh", "Refresh"),
    ]

    query_text: reactive[str | None] = reactive(None)

    def __init__(
        self,
        client: ShopifyClient,
        *,
        limit: int = 20,
        initial_query: str = "",
    ) -> None:
        super().__init__()
        self.client = client
        self.limit = limit
        self.query_text = initial_query or None
        self._entries: List[Dict[str, Any]] = []
        # Textual ids can't contain Shopify gid colons
        self._entry_map: Dict[str, Dict[str, Any]] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Static(id="chrome"):
            yield Input(
                placeholder="Search metaobjects… (e.g. type:namespace.key)",
                id="query",
                value=self.query_text or "",
            )
            with Horizontal(id="body"):
                yield ListView(id="results")
                yield Tree("Waiting for search…", id="detail")
            yield Static("", id="status")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_input.focus()
        if self.query_text:
            await self.perform_search(self.query_input.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "query":
            await self.perform_search(event.value.strip())

    async def action_focus_search(self) -> None:
        self.query_input.focus()

    async def action_refresh(self) -> None:
        await self.perform_search(self.query_input.value.strip())

    async def perform_search(self, query: str) -> None:
        if not query:
            self.set_status("Enter a query to search", style="yellow")
            return
        search_query = parse_search_query(query)
        normalized = search_query.normalized
        self.set_status(f"Searching with `{normalized or '…'}`", style="cyan")
        self.query_text = normalized
        try:
            results = await asyncio.to_thread(
                self.client.search_metaobjects, search_query, self.limit
            )
        except ShopifyAPIError as exc:
            self.post_message(SearchFailed(exc))
            return

        self._entries = results
        self._entry_map = {}
        list_view = self.results_view
        list_view.clear()

        if not results:
            self.set_status("No metaobjects matched that query 😢", style="yellow")
            self.detail_tree.root.label = "No results"
            self.detail_tree.refresh()
            return

        for idx, entry in enumerate(results):
            display = entry.get("displayName") or entry.get("handle") or entry["id"]
            subtitle = entry.get("type") or entry.get("definition", {}).get("type", "")
            safe_id = f"entry-{idx}"
            list_view.append(
                ListItem(
                    Static(
                        f"[b]{display}[/]\n[dim]{subtitle} · {entry.get('handle','—')}"
                    ),
                    id=safe_id,
                )
            )
            self._entry_map[safe_id] = entry

        list_view.index = 0
        await self.update_detail(results[0])
        self.set_status(
            f"Showing {len(results)} results for “{normalized or query}”.",
            style="green",
        )

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        entry = self.lookup_entry(event.item.id)
        if entry:
            await self.update_detail(entry)

    async def update_detail(self, entry: Dict[str, Any]) -> None:
        tree = self.detail_tree
        tree.clear()
        entry_type = entry.get("type") or entry.get("definition", {}).get("type", "")
        root_label = (
            f"[b]{entry.get('displayName') or entry.get('handle')}[/] [dim]{entry_type}"
        )
        root = tree.root
        root.label = root_label
        root.expanded = True
        root.add_leaf(f"Handle: {entry.get('handle','—')}")
        root.add_leaf(f"Updated: {entry.get('updatedAt','—')}")
        fields_node = root.add(f"[green]Fields[/]")
        for field in entry.get("fields", []):
            fields_node.add_leaf(
                f"[cyan]{field['key']}[/]: {field.get('value') or '—'}"
            )
        if not entry.get("fields"):
            fields_node.add_leaf("[dim]No fields[/]")
        tree.refresh()

    def lookup_entry(self, entry_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not entry_id:
            return None
        return self._entry_map.get(entry_id)

    def set_status(self, message: str, *, style: str = "white") -> None:
        status = self.query_one("#status", Static)
        status.update(f"[{style}]{message}[/{style}]")

    @property
    def query_input(self) -> Input:
        return self.query_one("#query", Input)

    @property
    def results_view(self) -> ListView:
        return self.query_one("#results", ListView)

    @property
    def detail_tree(self) -> Tree:
        return self.query_one("#detail", Tree)

    def on_search_failed(self, message: SearchFailed) -> None:
        self.set_status(str(message.error), style="red")
        self.detail_tree.root.label = "Error"
        self.detail_tree.refresh()
        self._entries = []
        self._entry_map = {}
        self.results_view.clear()
