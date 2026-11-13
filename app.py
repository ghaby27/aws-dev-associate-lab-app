"""Onward Logistics order system: one deployable that serves the UI and the order logic.

Orders are mocked in memory on each server (the lab does not ask for a database), so
each server shows only the orders it took. The page always shows which server answered:
an ECS task when it runs in a container on Fargate, an EC2 instance otherwise.
"""
import json
import math
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from itertools import count

from flask import Flask, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)

OWNER_NAME = os.environ.get("OWNER_NAME", "Gabriel Anyaele")
LAB_NAME = os.environ.get("LAB_NAME", "Handling Sales Day Demand for the Onward Logistics Order System")
APP_VERSION = os.environ.get("APP_VERSION", "dev")  # set to the commit SHA when the image is built
SPIKE_MINUTES = int(os.environ.get("SPIKE_MINUTES", "8"))

IMDS = "http://169.254.169.254/latest"
ECS_METADATA = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")  # set by ECS in every container


def _ecs_server():
    """Read the ECS task metadata endpoint. Returns None when not running on ECS."""
    if not ECS_METADATA:
        return None
    try:
        task = json.load(urllib.request.urlopen(f"{ECS_METADATA}/task", timeout=1))
        container = json.load(urllib.request.urlopen(ECS_METADATA, timeout=1))
        return {
            "kind": "ECS task",
            "instance_id": task["TaskARN"].rsplit("/", 1)[-1],
            "availability_zone": task.get("AvailabilityZone", "unknown"),
            "private_ip": container["Networks"][0]["IPv4Addresses"][0],
        }
    except (OSError, KeyError, IndexError, ValueError):
        return None


def _metadata(path):
    """Read EC2 instance metadata with IMDSv2. Returns None when not on EC2."""
    try:
        token_req = urllib.request.Request(
            f"{IMDS}/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        token = urllib.request.urlopen(token_req, timeout=1).read().decode()
        req = urllib.request.Request(f"{IMDS}/meta-data/{path}",
                                     headers={"X-aws-ec2-metadata-token": token})
        return urllib.request.urlopen(req, timeout=1).read().decode()
    except OSError:
        return None


# Looked up once at start-up: a server's identity never changes while it runs.
SERVER = _ecs_server() or {
    "kind": "EC2 instance",
    "instance_id": _metadata("instance-id") or socket.gethostname(),
    "availability_zone": _metadata("placement/availability-zone") or "local",
    "private_ip": _metadata("local-ipv4") or "127.0.0.1",
}
SERVER["version"] = APP_VERSION

_ids = count(1001)
ORDERS = []
PRICE_PER_KG = 4.50  # mock rate in USD


def create_order(merchant, destination, weight_kg):
    order = {
        "id": f"ORD-{next(_ids)}",
        "merchant": merchant,
        "destination": destination,
        "weight_kg": weight_kg,
        "price": round(5 + weight_kg * PRICE_PER_KG, 2),
        "created": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "server": SERVER["instance_id"],
    }
    ORDERS.insert(0, order)
    del ORDERS[50:]  # keep memory bounded
    return order


# A couple of sample orders so the page is never empty.
create_order("Kente Crafts", "Accra, Osu", 1.2)
create_order("Lagos Gadgets", "Lagos, Yaba", 3.5)


# ---------------------------------------------------------------------------
# Simulated bad release, for showing the automatic rollback. Uncomment, push to
# main, and keep scripts/watch.sh running: health checks still pass, so CodeDeploy
# moves traffic to this version; every page then returns 500, the 5xx alarm fires
# (more than 5 errors in a minute) and CodeDeploy moves traffic back to the old
# version on its own. Comment it out again and push, so main matches what runs.
# ---------------------------------------------------------------------------
# @app.before_request
# def simulated_bad_release():
#     if request.path != "/health":
#         return "Simulated bad release", 500


# ---------------------------------------------------------------------------
# Sales-day spike: a button on the page keeps this server's CPU busy for a few
# minutes, so auto scaling has something to react to. The burners use 80% of the
# server's CPU allocation (well above the 50% scaling target) at the lowest
# priority, so the app keeps answering pages and health checks during the spike.
# ---------------------------------------------------------------------------
SPIKE_SHARE = 0.8
_BURN = """
import os, sys, time
os.nice(19)
end, duty = time.time() + float(sys.argv[1]), float(sys.argv[2])
while time.time() < end:          # busy for duty x 10 ms, idle for the rest
    stop = time.perf_counter() + duty * 0.01
    while time.perf_counter() < stop:
        pass
    time.sleep((1 - duty) * 0.01)
"""
_spike = {"until": 0.0, "burners": []}


def _cpu_allocation():
    """CPUs this server may use: the Fargate task size, a container CPU limit, or all CPUs."""
    if ECS_METADATA:
        try:
            cpu = json.load(urllib.request.urlopen(f"{ECS_METADATA}/task", timeout=1))["Limits"]["CPU"]
            if cpu:
                return float(cpu)
        except (OSError, KeyError, ValueError, TypeError):
            pass
    try:
        quota, period = open("/sys/fs/cgroup/cpu.max").read().split()
        if quota != "max":
            return int(quota) / int(period)
    except (OSError, ValueError):
        pass
    return float(len(os.sched_getaffinity(0)))


def spike_until():
    """When the running spike ends (UTC "HH:MM:SS"), or None."""
    _spike["burners"] = [p for p in _spike["burners"] if p.poll() is None]  # reap finished ones
    if _spike["until"] <= time.time():
        return None
    return datetime.fromtimestamp(_spike["until"], timezone.utc).strftime("%H:%M:%S UTC")


@app.post("/spike")
def start_spike():
    if not spike_until():  # one spike at a time per server
        seconds = SPIKE_MINUTES * 60
        total = SPIKE_SHARE * _cpu_allocation()
        burners = max(1, math.ceil(total))
        for _ in range(burners):
            _spike["burners"].append(subprocess.Popen(
                [sys.executable, "-c", _BURN, str(seconds), str(total / burners)]))
        _spike["until"] = time.time() + seconds
    return redirect(url_for("index"))


@app.get("/")
def index():
    return render_template("index.html", owner=OWNER_NAME, lab=LAB_NAME, server=SERVER,
                           orders=ORDERS, error=request.args.get("error"),
                           spike_until=spike_until(), spike_minutes=SPIKE_MINUTES)


@app.post("/orders")
def place_order():
    merchant = request.form.get("merchant", "").strip()[:60]
    destination = request.form.get("destination", "").strip()[:60]
    try:
        weight = float(request.form.get("weight_kg", ""))
    except ValueError:
        weight = 0
    if not merchant or not destination or not 0 < weight <= 100:
        return redirect(url_for("index", error="Enter a merchant, a destination and a weight between 0 and 100 kg."))
    create_order(merchant, destination, weight)
    return redirect(url_for("index"))


@app.get("/api/whoami")
def whoami():
    """Small JSON answer for a curl loop that shows load balancing."""
    return jsonify(SERVER | {"spike_until": spike_until()})


@app.get("/health")
def health():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
