# Shopify Metaobject CLI

View + search Shopify metaobjects in a terminal using [Textual](https://github.com/Textualize/textual)


## Requirements

- Python 3.10+
- Shopify store domain (`example.myshopify.com`)
- Admin API access token with `read_metaobjects` + `read_metaobject_definitions`
- A smile on your face

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

```bash
# one-time config (writes ~/.shopmeta/config.json)
shopmetactl config set --store your-store.myshopify.com --token shpat_xxx

# dump a few definitions + sample entries
shopmetactl metaobjects tree --types 5 --entries 3

# inspect one type deeply
shopmetactl metaobjects view content_blocks.hero --limit 10

# export a definition + entries to JSON
shopmetactl metaobjects dump content_blocks.hero --out hero.json

# watch a type for edits
shopmetactl metaobjects watch content_blocks.hero --interval 2

# launch the Textual search UI
shopmetactl metaobjects search
```

#### Search
* Free-text search (e.g. `hero banner`) matches display names, handles, and field values

* Add `type:` if you want to filter by namespace/key (`type:namespace.key`, `type:namespace.*`, `.key`)

* Flags `--namespace` / `--key` do the same without typing `type:`

## Configuration

- Stored config lives in `~/.shopmeta/config.json`. Set `SHOPMETA_STORE`, `SHOPMETA_TOKEN`, and `SHOPMETA_API_VERSION` to override per run
- Admin GraphQL version defaults to `2025-10`, override with `--api-version` when Shopify bumps schemas

## Notes

- The Textual UI uses pagination-free queries. Large stores may take a few seconds, Shopify caps metaobject definition pagination at 50 per request
- Search pulls definitions client-side and filters in Python because the GraphQL `metaobjects(query:)` search currently requires an exact type
- `dump` writes definition + entry JSON snapshots for deploy diffs. `watch` polls every few seconds and highlights rows where `updatedAt` changed (cheap way to keep content synced during launch rushes)
- If Textual output glitches, force-truecolor: `export COLORTERM=truecolor`
