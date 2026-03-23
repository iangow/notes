# notes

Python dependencies in this repository are managed with `uv`.

## Setup

Create the project environment:

```sh
uv sync
```

If you use RStudio with `reticulate`, the project is configured to use `.venv/bin/python`.

## Common commands

Render or preview Quarto content through the `uv` environment:

```sh
uv run quarto preview published/bb68.qmd --no-browser --no-watch-inputs
```

Check the Python environment seen by `uv`:

```sh
uv run python -c "import sys; print(sys.executable)"
```
