FROM python:3.11-slim
WORKDIR /app
COPY ./app /app/app
RUN pip install gradio
CMD ["python", "-m", "app.main"]
