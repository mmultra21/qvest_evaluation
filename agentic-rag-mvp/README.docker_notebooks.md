# Running notebooks inside Docker

This document explains how to build and run a Docker image that contains JupyterLab and can optionally execute the notebooks in `docs/` non-interactively using papermill.

## Build the image

```bash
# build locally (from repo root)
docker build -t qvest-notebooks:local .
```

## Run a container with interactive Jupyter Lab

```bash
# start a container and open Jupyter at http://localhost:8888
docker run --rm -p 8888:8888 -v "$(pwd)":/work qvest-notebooks:local
```

## Run the notebooks non-interactively on container start

1. Edit `docker-compose.notebooks.yml` and set `RUN_NOTEBOOKS=true` under the `notebooks` service `environment` section, or pass the environment variable on `docker run`.

```bash
# example: run with environment variable
docker run --rm -p 8888:8888 -v "$(pwd)":/work -e RUN_NOTEBOOKS=true qvest-notebooks:local
```

Outputs will be placed in `notebook_outputs/` (or the container's `/work/notebook_outputs`), which is mounted back to your host by the compose file.

## Notes & tips

- External services (Qdrant, Hermes3) should be run as separate containers and connected via environment variables (e.g., `QDRANT_URL=http://qdrant:6333`).
- Do not bake secrets into images; use `.env` or Docker secrets.
- If papermill runs fail due to missing packages, add them to `requirements.txt` or `requirements-notebook.txt` and rebuild.
- For reproducible environments in Binder/Codespaces, provide an `environment.yml` or devcontainer config.  
