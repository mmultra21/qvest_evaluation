# Dockerfile to run JupyterLab and optionally execute notebooks with papermill
FROM python:3.11-slim

# Create non-root user
ENV USER=appuser
RUN groupadd -r $USER && useradd -r -g $USER $USER

# Install minimal system deps (adjust if additional libs are needed)
RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential gcc curl git \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /work

# Copy dependency manifests early for better cache
COPY requirements-notebook.txt /work/requirements-notebook.txt
# If your project has requirements.txt, also copy it (optional)
COPY requirements.txt /work/requirements.txt

# Install notebook-specific dependencies first
RUN pip install --no-cache-dir -r /work/requirements-notebook.txt || true
# Install project dependencies if present (non-fatal if file missing)
RUN if [ -f /work/requirements.txt ]; then pip install --no-cache-dir -r /work/requirements.txt || true; fi

# Copy the app repo into the image
COPY . /work
RUN chown -R $USER:$USER /work

USER $USER
ENV PYTHONUNBUFFERED=1

# Expose Jupyter default port
EXPOSE 8888

# Copy helper script and ensure it is executable
COPY run_notebooks.sh /work/run_notebooks.sh
RUN chmod +x /work/run_notebooks.sh

# Default: run the helper which optionally executes notebooks and then starts Jupyter Lab
ENTRYPOINT ["/work/run_notebooks.sh"]
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--NotebookApp.token=''"]
