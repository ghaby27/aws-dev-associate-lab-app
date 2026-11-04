# Onward Logistics Order App

A single full-stack Python (Flask) app for the Onward Logistics lab: it serves the order UI and the order logic together. The page shows the owner, the lab name and which server answered (instance ID, Availability Zone, private IP). Orders are mocked in memory on each server.

| Route | Purpose |
|---|---|
| `/` | Order page |
| `POST /orders` | Place an order |
| `/api/whoami` | JSON: which server answered |
| `/health` | Load balancer health check |

Servers clone this repository at boot and run it with gunicorn on port 8080 as the `onward-orders` systemd service (`onward-orders.service`), reading `OWNER_NAME` and `LAB_NAME` from `/etc/onward/orders.env`. The infrastructure lives in [week3-aws-lab-sales-demand](https://github.com/ghaby27/week3-aws-lab-sales-demand).

Run locally:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py   # http://localhost:8080
```
