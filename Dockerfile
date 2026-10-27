# Steps 27-28: the same image runs in every environment (local -> CI -> Render)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# build data, model and web desk inside the image, and refuse to build if tests fail
RUN python src/generate_data.py && python src/train.py && python src/build_app.py && pytest -q
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn src.api:app --host 0.0.0.0 --port ${PORT}"]
