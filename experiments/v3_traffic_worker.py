#!/usr/bin/env python3
"""Bounded traffic worker. Every destination is fixed inside the Mininet lab."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import random
import shutil
import socket
import subprocess
import time

TARGET_IP = "10.0.0.100"


def http_request(path="/"):
    connection = http.client.HTTPConnection(TARGET_IP, 80, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        return response.status == 200
    except (OSError, TimeoutError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def ping_once():
    try:
        return subprocess.run(["ping", "-c", "1", "-W", "1", TARGET_IP],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=2).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def udp_sink(duration):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((TARGET_IP, 9000))
    sock.settimeout(.5)
    deadline = time.monotonic() + duration
    packets = 0
    try:
        while time.monotonic() < deadline:
            try:
                sock.recvfrom(4096)
                packets += 1
            except socket.timeout:
                pass
    finally:
        sock.close()
    print(json.dumps({"udp_sink_packets": packets}), flush=True)


def benign(spec, deadline):
    parameters = spec["parameters"]
    behavior = spec["profile_behavior"]
    rng = random.Random(parameters["seed"])
    payload = bytes(rng.getrandbits(8) for _ in range(parameters["payload_bytes"]))
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    successes = 0
    attempts = 0
    start = time.monotonic()
    try:
        while time.monotonic() < deadline:
            phase = (time.monotonic() - start) % 6
            if behavior == "ping_http":
                attempts += 2
                successes += int(ping_once()) + int(http_request("/?v3=benign"))
                time.sleep(min(parameters["request_pause_seconds"], max(0, deadline-time.monotonic())))
            elif behavior == "low_udp":
                udp.sendto(payload, (TARGET_IP, 9000))
                attempts += 1
                successes += 1
                time.sleep(min(1 / parameters["udp_pps"], max(0, deadline-time.monotonic())))
            elif behavior == "low_tcp":
                attempts += 1
                successes += int(http_request("/?v3=normal"))
                time.sleep(min(parameters["request_pause_seconds"], max(0, deadline-time.monotonic())))
            elif behavior == "idle_bursty_mixed":
                if phase < parameters["idle_seconds_per_cycle"]:
                    time.sleep(min(.1, max(0, deadline-time.monotonic())))
                else:
                    udp.sendto(payload, (TARGET_IP, 9000))
                    attempts += 1
                    successes += 1
                    if attempts % 10 == 0:
                        attempts += 2
                        successes += int(ping_once()) + int(http_request("/?v3=mixed"))
                    time.sleep(min(1 / parameters["udp_pps"], max(0, deadline-time.monotonic())))
            else:
                raise ValueError("unknown BENIGN behavior")
    finally:
        udp.close()
    print(json.dumps({"attempts": attempts, "successful_operations": successes}), flush=True)


def hping(spec, deadline):
    parameters = spec["parameters"]
    binary = shutil.which("hping3")
    if not binary:
        raise RuntimeError("hping3 is required inside the lab")
    interval_us = max(1, round(1_000_000 / parameters["requested_pps"]))
    command = [binary, "-2" if spec["scenario_label"] == "UDP_FLOOD" else "-S",
               "-n", "-q", "-i", "u%s" % interval_us,
               "-p", str(parameters["destination_port"])]
    if parameters["payload_bytes"]:
        command += ["-d", str(parameters["payload_bytes"])]
    command += [TARGET_IP]
    cycles = 0
    while time.monotonic() < deadline:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        on_seconds = parameters["burst_on_seconds"] or (deadline-time.monotonic())
        probe = min(.2, max(0, deadline-time.monotonic()))
        time.sleep(probe)
        if process.poll() is not None:
            raise RuntimeError("hping3 exited early with code %s" % process.returncode)
        time.sleep(min(max(0, on_seconds-probe), max(0, deadline-time.monotonic())))
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        cycles += 1
        off_seconds = parameters["burst_off_seconds"]
        if off_seconds:
            time.sleep(min(off_seconds, max(0, deadline-time.monotonic())))
    print(json.dumps({"hping_command": command, "cycles": cycles}), flush=True)


def http_load(spec, deadline):
    parameters = spec["parameters"]
    rng = random.Random(parameters["seed"])
    concurrency = parameters["concurrency"]
    padding = "x" * parameters["uri_padding_bytes"]
    attempts = successes = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while time.monotonic() < deadline:
            path = "/?v3=load&pad=%s&nonce=%08x" % (padding, rng.getrandbits(32))
            results = list(pool.map(http_request, [path] * concurrency))
            attempts += len(results)
            successes += sum(results)
            pause = parameters["batch_pause_seconds"] * rng.uniform(.8, 1.2)
            if spec["profile_behavior"] == "bursty" and attempts % (concurrency * 5) == 0:
                pause += 1.5
            time.sleep(min(pause, max(0, deadline-time.monotonic())))
    print(json.dumps({"http_requests": attempts, "http_200": successes}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-json")
    parser.add_argument("--udp-sink", action="store_true")
    parser.add_argument("--duration", type=float)
    args = parser.parse_args()
    if args.udp_sink:
        if args.duration is None or args.duration <= 0:
            parser.error("UDP sink needs a positive duration")
        udp_sink(args.duration)
        return
    if not args.spec_json:
        parser.error("--spec-json is required")
    spec = json.loads(args.spec_json)
    parameters = spec["parameters"]
    if parameters["target_ip"] != TARGET_IP or not 1 <= parameters["duration_seconds"] <= 60:
        raise ValueError("worker target or duration outside fixed lab bounds")
    deadline = time.monotonic() + parameters["duration_seconds"]
    scenario = spec["scenario_label"]
    if scenario == "BENIGN":
        benign(spec, deadline)
    elif scenario in ("UDP_FLOOD", "TCP_SYN_LIKE"):
        hping(spec, deadline)
    elif scenario == "HTTP_FLOOD":
        http_load(spec, deadline)
    else:
        raise ValueError("unknown scenario")


if __name__ == "__main__":
    main()
