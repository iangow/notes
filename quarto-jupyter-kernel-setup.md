## Quarto Python environment setup

This note records a practical setup for Quarto projects that use a repo-local `.venv`.

## Jupyter engine documents

For `.qmd` files that use Quarto's Jupyter engine:

1. Sync the repo-local virtual environment:
   ```sh
   uv sync
   ```

2. Register the repo `.venv` as a named Jupyter kernel:
   ```sh
   uv run ipython kernel install --user --env VIRTUAL_ENV $(pwd)/.venv --name <kernel-name> --display-name <kernel-name>
   ```

3. In the `.qmd` YAML, specify the kernel explicitly:
   ```yaml
   engine: jupyter
   jupyter: <kernel-name>
   ```

This is preferable to relying on Quarto or the editor to guess the correct kernel.

## knitr documents that use Python

For `.qmd` files that use `engine: knitr` together with Python chunks via `reticulate`, a practical single-machine approach is to set `RETICULATE_PYTHON` in a local `.Renviron` file using an absolute path:

```sh
RETICULATE_PYTHON=/absolute/path/to/repo/.venv/bin/python
```

This is simple and reliable for local use.

## Why this is needed

A local `.venv` by itself is not enough to guarantee that Quarto will select the right Python environment.

- Jupyter-engine documents execute through Jupyter kernelspecs.
- knitr documents using Python rely on `reticulate`.

So the reliable pattern is:

- Jupyter engine: name the kernel in YAML
- knitr + Python: set `RETICULATE_PYTHON`

## Example

From the repository root:

```sh
uv sync
uv run ipython kernel install --user --env VIRTUAL_ENV $(pwd)/.venv --name notes --display-name notes
```

Then in a Jupyter-backed `.qmd`:

```yaml
engine: jupyter
jupyter: notes
```

And for a local `.Renviron` used by `knitr` + `reticulate`:

```sh
RETICULATE_PYTHON=/Users/igow/git/notes/.venv/bin/python
```
