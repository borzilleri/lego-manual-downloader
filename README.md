[![CI](https://github.com/borzilleri/lego-manual-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/borzilleri/lego-manual-downloader/actions/workflows/ci.yml)


## Install/Setup

Copy the [config.example.toml](./config.example.toml) to `~/.config/lego-manual-downloader/config.toml` and edit it with appropriate values.

## Usage

```
lego-manual-downloader <download-dir> [--config PATH] [--dry-run]
```

`<download-dir>` must already exist and be writable. Manuals are written there as
`<number>-<variant> <name> (<year>).pdf`, alongside a small JSON database recording what has
already been fetched, so repeat runs only download what is missing.

`--dry-run` reports which manuals would be downloaded without writing anything — no PDFs and no
database. It still contacts each provider to check availability, so unavailable sets are reported
just as they would be on a real run.
