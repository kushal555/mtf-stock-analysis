FROM python:3.11-slim

WORKDIR /app

COPY . /app

EXPOSE 5050

ENV PORT=5050
ENV DASHBOARD_HOST=0.0.0.0

CMD ["python3", "dashboard.py"]
