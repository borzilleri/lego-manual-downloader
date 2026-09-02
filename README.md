[![CI](https://github.com/borzilleri/lego-manual-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/borzilleri/lego-manual-downloader/actions/workflows/ci.yml)


## Install/Setup

Copy the [config.example.toml](./config.example.toml) to `~/.config/lego-manual-downloader/config.toml` and edit it with appropriate values.

## Usage

```
lego-manual-downloader <download-dir> [--config PATH] [--dry-run]
                       [--log-level LEVEL] [--log-file PATH] [--no-color]
```

`<download-dir>` must already exist and be writable. Manuals are written there as
`<number>-<variant> <name> (<year>).pdf`, alongside a small JSON database recording what has
already been fetched, so repeat runs only download what is missing.

`--dry-run` reports which manuals would be downloaded without writing anything — no PDFs and no
database. It still contacts each provider to check availability, so unavailable sets are reported
just as they would be on a real run.

## Output

`--log-level` takes `debug`, `info` (the default), `warning`, or `error`. At the default level each
manual downloaded, skipped, or renamed is reported; `debug` adds a line per set as it is
considered, and `warning` reports only what went wrong.

Progress goes to stdout and warnings and errors to stderr, so either half can be redirected on its
own. Levels other than `info` are tagged and colored when the destination is a terminal; set
`NO_COLOR` or pass `--no-color` to suppress that. `--log-file PATH` additionally writes every line,
timestamped and uncolored, to a file.

Both the level and the log file can be set persistently in a `[logging]` section of the config
file; the command-line flags win.
