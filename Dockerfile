FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app

# boto3 is the only dependency, and only because the data tier is S3. The
# dashboard itself is stdlib.
RUN pip install --no-cache-dir "boto3==1.35.99"

COPY quakes.py app.py refresh.py agent.py ./
COPY data/ ./data/
COPY static/ ./static/
RUN useradd --create-home --uid 10001 astro && chown -R astro:astro /app
USER astro
EXPOSE 8080
CMD ["python", "app.py"]
