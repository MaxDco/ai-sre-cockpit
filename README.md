# AI SRE Cockpit

Autonomous observability and AI incident analysis stack built with Prometheus, Alertmanager, Grafana, Loki, Alloy, FastAPI, and DeepSeek API.

## Quick Start

1. Copy env template: cp .env.example .env
2. Add your DEEPSEEK_API_KEY in .env
3. Start stack: docker compose up -d --build

## Endpoints

- Grafana: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- Prometheus: [http://127.0.0.1:9090](http://127.0.0.1:9090)
- Alertmanager: [http://127.0.0.1:9093](http://127.0.0.1:9093)
- AI SRE Manager: [http://127.0.0.1:8000](http://127.0.0.1:8000)
