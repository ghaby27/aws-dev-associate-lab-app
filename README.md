# Onward Logistics Order App

A single full-stack Python (Flask) app for the Onward Logistics labs: it serves the order UI and the order logic together. The page shows the owner, the lab name, the running version and which server answered (ECS task or EC2 instance, Availability Zone, private IP). Orders are mocked in memory on each server.

| Route | Purpose |
|---|---|
| `/` | Order page |
| `POST /orders` | Place an order |
| `/api/whoami` | JSON: which server and version answered |
| `/health` | Load balancer health check |

## How it is released (ECS lab)

Infrastructure: [week3-aws-lab-safe-delivery](https://github.com/ghaby27/week3-aws-lab-safe-delivery).

1. Merge to `main` (changes to the app, `Dockerfile` or `deploy/`).
2. `.github/workflows/release.yml` builds the image, signs in to AWS with GitHub's OIDC token (no stored keys) and pushes it to ECR as `<commit sha>` and `latest`.
3. EventBridge sees the `latest` push and starts CodePipeline.
4. CodePipeline takes the image and `deploy/` from this repository: `taskdef.json` (the task definition, with `<IMAGE1_NAME>` replaced by the new image) and `appspec.yaml` (which container and port get traffic).
5. CodeDeploy starts the new tasks beside the old ones, moves traffic once they are healthy, and rolls back on failure.

| File | Purpose |
|---|---|
| `Dockerfile` | The image: gunicorn on port 8080, runs as a non-root user |
| `.github/workflows/release.yml` | Build and push on merge (also runnable by hand) |
| `deploy/taskdef.json` | Task definition for each release (CPU, memory, roles, logs, environment) |
| `deploy/appspec.yaml` | CodeDeploy blue/green: container `orders`, port 8080 |

## EC2 lab

For [week3-aws-lab-sales-demand](https://github.com/ghaby27/week3-aws-lab-sales-demand), servers clone this repository at boot and run it with gunicorn on port 8080 as the `onward-orders` systemd service (`onward-orders.service`), reading `OWNER_NAME` and `LAB_NAME` from `/etc/onward/orders.env`.

## Run locally

```bash
docker build -t onward-orders . && docker run --rm -p 8080:8080 onward-orders   # http://localhost:8080
```

or without Docker:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```
