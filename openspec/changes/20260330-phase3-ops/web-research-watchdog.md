# Web Research: Bash Process Supervision, Watchdog Patterns & Crash Loop Protection

**Date**: 2026-03-30
**Keywords searched**:
1. `bash process supervisor watchdog heartbeat pattern 2025 2026`
2. `bash crash loop protection auto restart best practices`
3. `Python bot process management systemd vs bash wrapper`
4. `systemd WatchdogSec heartbeat Python process sd_notify WATCHDOG=1`
5. `bash process restart exponential backoff crash loop cooldown pattern`
6. `supervisord vs systemd vs bash wrapper process management production comparison`

---

## Source 1: watchdogd — Advanced System Monitor & Process Supervisor

**URL**: https://github.com/troglobit/watchdogd

### Excerpts

> "periodically kicks the system watchdog timer (WDT) to prevent it from resetting the system"

> "as long as there is CPU time it 'kicks' /dev/watchdog every 10 seconds"

> "supervises the heartbeat of processes, records deadline transgressions, and initiates a controlled reset if needed"

Monitoring capabilities include: file descriptor leaks, file system usage, memory leaks, process live locks, load average monitoring, temperature monitoring.

### Takeaways

- Industry-grade watchdog daemon for embedded Linux / server systems
- Heartbeat-based: monitored processes must periodically signal; failure to do so triggers restart
- Default kick interval: 10 seconds
- Covers more than just process liveness (memory, FD leaks, load)

---

## Source 2: processWatchdog — Linux Process Monitor with Heartbeat

**URL**: https://github.com/diffstorm/processWatchdog

### Excerpts

> "It ensures the continuous operation of these processes by periodically checking their status and restarting them if necessary."

> "If a process fails to send a heartbeat within the specified time interval, the watchdog manager assumes the process has halted/hang and automatically restarts it."

> "Set the `heartbeat_interval` config to zero to skip heartbeat checks for given processes."

**Configuration format (config.ini)**:
```ini
[processWatchdog]
udp_port = 12345

[app:Communicator]
start_delay = 10
heartbeat_delay = 60
heartbeat_interval = 20
cmd = /usr/bin/python test_child.py 1 crash
```

**Python heartbeat sender**:
```python
import socket, os
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
pid = f"p{os.getpid()}"
sock.sendto(pid.encode(), ('127.0.0.255', port))
```

### Takeaways

- Two monitoring modes: heartbeat-based (UDP packets with PID) and non-heartbeat (existence check)
- `heartbeat_interval = 0` disables heartbeat checks (useful for simple processes)
- `heartbeat_delay` gives process startup grace period before heartbeat checks begin
- Tracks crash counts, restart counts, and timestamps per process

---

## Source 3: Squash.io — Using a Watchdog Process to Trigger Bash Scripts

**URL**: https://www.squash.io/using-a-watchdog-process-to-trigger-bash-scripts-in-linux/

### Excerpts

> "It periodically sends a heartbeat signal to the system, and if it fails to receive the expected response, it assumes that the system or application has crashed."

> Scripts should "execute quickly and efficiently"

> Implement "error handling mechanisms, logging errors, and taking appropriate actions"

> Adjust timeout values based on system performance characteristics

### Takeaways

- Generic overview of kernel-level and user-space watchdog mechanisms
- Best practice: keep watchdog scripts fast and focused
- Adjust timeouts to match actual system characteristics (not one-size-fits-all)

---

## Source 4: Paepper.com — Bash: Keep Script Running, Restart on Crash

**URL**: https://www.paepper.com/blog/posts/bash-keep-script-running-restart-on-crash/

### Excerpts

**Core pattern using `until` loop**:
```bash
#!/bin/bash

until python test.py
do
    echo "Restarting"
    sleep 2
done
```

> "When you are prototyping and developing small scripts that you keep running, it might be annoying that they quit when an error occurs."

The `until` construct executes a command repeatedly until it succeeds (returns exit code 0). The `sleep 2` provides a 2-second pause before attempting to restart, preventing rapid-fire restarts.

### Takeaways

- Simplest bash supervision pattern: `until <command>; do sleep N; done`
- Good for development/prototyping, lacks production features (no crash counting, no backoff)
- No signal forwarding, no graceful shutdown handling
- Sleep between restarts is essential to prevent tight restart loops

---

## Source 5: Baeldung — Keep Programs Alive During a Crash or Reboot

**URL**: https://www.baeldung.com/linux/process-continuous-running-after-crash-reboot (403 — content from search summary)

### Excerpts (from search results)

> "The simplest approach is to wrap the execution of your script or program within an infinite loop... However, this approach lacks sophistication—you can't monitor the status of the program running, you can't stop it any other way but by sending the kill signal, and if the whole system crashes, the program won't automatically be executed again."

> For "system-critical services, systemd offers a robust and integrated solution, whereas supervisord provides more control for managing multiple processes. For simple tasks, a bash loop and a cron job should suffice."

### Takeaways

- Three tiers: bash loop (simple) < cron + script (moderate) < systemd/supervisord (production)
- Bash loop cannot survive system reboot
- Systemd for system-critical; supervisord for multi-process management; bash for simple tasks

---

## Source 6: TechMint — How to Restart Programs After a Crash or Reboot

**URL**: https://www.tecmint.com/linux-process-running-after-crash-reboot/

### Excerpts

**Systemd service file**:
```ini
[Unit]
Description=My Application

[Service]
ExecStart=/path/to/myapp
Restart=always

[Install]
WantedBy=default.target
```

**Bash keep-alive script**:
```bash
#!/bin/bash

# Check if the app is running
if ! pgrep -x "myapp" > /dev/null
then
    # If not, restart the app
    /path/to/myapp
fi
```

**Cron scheduling**:
```
* * * * * /path/to/keep_alive_script.sh
```

**Supervisord configuration**:
```ini
[program:myapp]
command=/path/to/your/application
autostart=true
autorestart=true
stderr_logfile=/var/log/myapp.err.log
stdout_logfile=/var/log/myapp.out.log
```

### Takeaways

- `pgrep -x` is the standard way to check process existence in bash
- Cron-based approach: 1-minute granularity, good enough for non-critical services
- Supervisord: `autostart=true` + `autorestart=true` covers boot and crash recovery
- systemd `Restart=always`: simplest production config

---

## Source 7: TechMint — How to Automatically Restart a Failed Service in Linux

**URL**: https://www.tecmint.com/automatically-restart-service-linux/

### Excerpts

**Restart policies**:
- `Restart=always` — "The service always restarts, even if it was manually stopped."
- `Restart=on-failure` — "Restarts only if the service exits with an error (but not if stopped manually)."
- `Restart=on-abnormal` — "Restarts the service if it crashes due to a signal (like a segmentation fault)."
- `Restart=on-watchdog` — "Restart the service if it times out while running."

**RestartSec**:
> "Tells systemd to wait 5 seconds before restarting the service, which can prevent rapid restart loops in case of repeated failures."

**Minimal override**:
```ini
[Service]
Restart=always
RestartSec=5s
```

### Takeaways

- Four restart policies covering different failure modes
- `Restart=on-watchdog` specifically for heartbeat timeout scenarios
- `RestartSec` is the primary rapid-restart prevention mechanism in systemd

---

## Source 8: OneUptime — Configure systemd RestartSec and WatchdogSec on Ubuntu (2026-03-02)

**URL**: https://oneuptime.com/blog/post/2026-03-02-configure-systemd-restartsec-watchdogsec-ubuntu/view

### Excerpts

**WatchdogSec configuration**:
```ini
[Service]
Type=notify
WatchdogSec=30s
Restart=on-watchdog
RestartSec=5s
```

> "The service must send `sd_notify(STATUS=WATCHDOG=1)` (or equivalent) to systemd within the watchdog timeout period, or systemd kills and restarts it."

> `Type=notify` is required; systemd waits for a `READY=1` notification before considering the service started.

**Crash loop protection (StartLimitIntervalSec + StartLimitBurst)**:
```ini
[Unit]
StartLimitIntervalSec=60s
StartLimitBurst=5
StartLimitAction=none
```

> "With these settings: 1) Service fails and restarts after 5 seconds 2) After 5 restarts within 60 seconds, systemd stops trying 3) The service enters a 'failed' state 4) Manual intervention is required."

**RestartSec guidance**:
> "The right value depends on the failure mode" — transient errors typically need 2-5 seconds, while initialization failures benefit from 10-30 second delays.

**Complete production unit file**:
```ini
[Unit]
Description=Reliable API Service
After=network.target postgresql.service
Requires=postgresql.service
StartLimitIntervalSec=120s
StartLimitBurst=5

[Service]
Type=notify
User=apiservice
Group=apiservice
ExecStart=/usr/local/bin/api-server
Restart=on-failure
RestartSec=5s
WatchdogSec=30s
TimeoutStartSec=60s
TimeoutStopSec=30s
KillMode=mixed
KillSignal=SIGTERM
Environment=PORT=8080
Environment=LOG_LEVEL=info
MemoryMax=1G
CPUQuota=100%
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
StateDirectory=apiservice
LogsDirectory=apiservice
RuntimeDirectory=apiservice

[Install]
WantedBy=multi-user.target
```

**Python sd_notify implementation**:
```python
import os
import socket
import time

def notify_systemd(state: str):
    """Send notification to systemd via sd_notify socket."""
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return

    if notify_socket.startswith("@"):
        notify_socket = "\0" + notify_socket[1:]

    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(notify_socket)
        sock.sendall(state.encode())

def main():
    notify_systemd("READY=1\nSTATUS=Service is running")

    while True:
        try:
            process_work()
            notify_systemd("WATCHDOG=1")
        except Exception as e:
            print(f"Error: {e}", flush=True)

        time.sleep(10)
```

### Takeaways

- **WatchdogSec + Type=notify**: the gold standard for heartbeat-based process supervision in systemd
- **StartLimitIntervalSec + StartLimitBurst**: systemd's built-in crash loop protection
- **RestartSec**: 2-5s for transient errors, 10-30s for init failures
- **KillMode=mixed**: sends SIGTERM to main process, SIGKILL to remaining after timeout
- **TimeoutStopSec**: graceful shutdown window before SIGKILL
- Service must call `READY=1` on startup and `WATCHDOG=1` periodically (at half WatchdogSec interval)

---

## Source 9: Spindel's Gist — Systemd Watchdog in Python (Complete Example)

**URL**: https://gist.github.com/Spindel/1d07533ef94a4589d348

### Excerpts

**Key functions (verbatim)**:

```python
def watchdog_period():
    """Return the time (in seconds) that we need to ping within."""
    val = os.environ.get("WATCHDOG_USEC", None)
    if not val:
        return None
    return int(val) / 1000000

def notify_socket(clean_environment=True):
    """Return a tuple of address, socket for future use."""
    _empty = None, None
    address = os.environ.get("NOTIFY_SOCKET", None)
    if clean_environment:
        address = os.environ.pop("NOTIFY_SOCKET", None)
    if not address:
        return _empty
    if len(address) == 1:
        return _empty
    if address[0] not in ("@", "/"):
        return _empty
    if address[0] == "@":
        address = "\0" + address[1:]

    try:
        sock = socket.socket(
            socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC
        )
    except AttributeError:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    return address, sock

def sd_message(address, sock, message):
    """Send a message to the systemd bus/socket."""
    if not (address and sock and message):
        return False
    assert isinstance(message, bytes)
    try:
        retval = sock.sendto(message, address)
    except socket.error:
        return False
    return retval > 0

def watchdog_ping(address, sock):
    """Helper function to send a watchdog ping."""
    message = b"WATCHDOG=1"
    return sd_message(address, sock, message)
```

**Service file**:
```ini
[Unit]
Description=Watchdog example service

[Service]
Type=notify
Environment=PROBABILITY=0.4
ExecStart=/tmp/1d07533ef94a4589d348/watchdogged.py
Restart=always
RestartSec=30
WatchdogSec=1

[Install]
WantedBy=multi-user.target
```

### Takeaways

- **WATCHDOG_USEC** environment variable: systemd tells the service its watchdog interval in microseconds
- Clean environment pattern: `os.environ.pop("NOTIFY_SOCKET")` prevents child processes from inheriting
- Abstract socket handling: `@` prefix converted to `\0` for AF_UNIX
- `SOCK_CLOEXEC` flag prevents socket leak to child processes
- Ping at `period - 0.01` (slightly under the deadline) — safety margin approach

---

## Source 10: stigok.com — sd_notify and systemd watchdog in Python 3

**URL**: https://blog.stigok.com/2020/01/26/sd-notify-systemd-watchdog-python-3.html

### Excerpts

> "The package itself is a tiny client library to interface with the systemd watchdog functionality and sd-notify(3)."

Uses `sd-notify` PyPI package with `Notifier` class:
```python
notify = sd_notify.Notifier()
if not notify.enabled():
    raise Exception("Watchdog not enabled")
```

Service configuration:
- `Type=notify` — "A systemd service of Type=notify waits for the executable program to send a notification message to systemd"
- `WatchdogSec=15` — Service expects heartbeat messages within 15-second intervals
- `Restart=on-failure` and `RestartSec=10` for recovery

### Takeaways

- `sd-notify` PyPI package simplifies integration vs raw socket code
- `WatchdogSec=15` is a reasonable default for Python services
- `Notifier.enabled()` check allows graceful degradation when not running under systemd

---

## Source 11: Coderwall — Exponential Backoff in Bash

**URL**: https://coderwall.com/p/--eiqg/exponential-backoff-in-bash

### Excerpts

```bash
function with_backoff {
  local max_attempts=${ATTEMPTS-5}
  local timeout=${TIMEOUT-1}
  local attempt=0
  local exitCode=0

  while [[ $attempt < $max_attempts ]]
  do
    "$@"
    exitCode=$?

    if [[ $exitCode == 0 ]]
    then
      break
    fi

    echo "Failure! Retrying in $timeout.." 1>&2
    sleep $timeout
    attempt=$(( attempt + 1 ))
    timeout=$(( timeout * 2 ))
  done

  if [[ $exitCode != 0 ]]
  then
    echo "You've failed me for the last time! ($@)" 1>&2
  fi

  return $exitCode
}
```

> "The retry count is given by ATTEMPTS (default 5), the initial backoff timeout is given by TIMEOUT in seconds (default 1.) Successive backoffs double the timeout."

### Takeaways

- Classic exponential backoff: 1s, 2s, 4s, 8s, 16s (geometric doubling)
- Configurable via environment variables (ATTEMPTS, TIMEOUT)
- Warning about `set -e` — can kill the whole script on first failure

---

## Source 12: GitHub Gist — Bash Retry with Exponential Backoff (Quadratic)

**URL**: https://gist.github.com/28611bfaa2395072119464521d48729a

### Excerpts

```bash
function err_retry() {
  local exit_code=$1
  local attempts=$2
  local sleep_millis=$3
  shift 3

  for attempt in `seq 1 $attempts`; do
    if [[ $attempt -gt 1 ]]; then
      echo "Attempt $attempt of $attempts"
    fi

    "$@" && local rc=$? || local rc=$?

    if [[ ! $rc -eq $exit_code ]]; then
      return $rc
    fi

    if [[ $attempt -eq $attempts ]]; then
      return $rc
    fi

    local sleep_ms="$(($attempt * $attempt * $sleep_millis))"
    sleep "${sleep_ms:0:-3}.${sleep_ms: -3}"
  done
}
```

> Wait intervals increase quadratically (`attempt * attempt * sleep_millis`).

### Takeaways

- Quadratic backoff variant (1x, 4x, 9x, 16x, 25x multiplier)
- Retries only on specific exit code (selective retry)
- Millisecond-precision sleep using string slicing trick

---

## Source 13: Medium — 12 Bash Scripts for Intelligent Retry & Error Recovery

**URL**: https://medium.com/@obaff/12-bash-scripts-to-implement-intelligent-retry-backoff-error-recovery-a02ab682baae

### Excerpts

**Exponential backoff pattern**:
```bash
exp_backoff() {
  local max_attempts=$1
  local cmd="${@:2}"
  local delay=1

  for attempt in $(seq 1 "$max_attempts"); do
    echo "Attempt $attempt..."
    if eval "$cmd"; then
      return 0
    fi

    echo "Retrying in $delay seconds..."
    sleep "$delay"
    delay=$(( delay * 2 ))
  done

  return 1
}

exp_backoff 5 "curl -fsS https://my-api/ping"
```

> "Exponential backoff is the industry best practice for unreliable services. It reduces pressure on systems that are already overloaded."

### Takeaways

- Exponential backoff is industry best practice
- Reduces pressure on overloaded downstream systems
- Jitter (random component) mentioned but not shown in available excerpt

---

## Source 14: Kubernetes CrashLoopBackOff (Reference Pattern)

**URL**: https://docs.cloud.google.com/kubernetes-engine/docs/troubleshooting/crashloopbackoff-events (from search results)

### Excerpts (from search summary)

> "With each failed restart, the BackOff delay before the next attempt increases exponentially (for example, 10s, 20s, 40s), up to a maximum of five minutes."

> "Rather than repeatedly deleting and restarting, you should fix the root cause; the kubelet's exponential backoff will subside once the container becomes healthy."

### Takeaways

- Kubernetes uses exponential backoff with a **5-minute cap** for crash loops
- Pattern: 10s -> 20s -> 40s -> 80s -> 160s -> 300s (cap)
- Once healthy, backoff resets — no permanent penalty for past failures

---

## Source 15: DEV.to — Python Developer's Guide to Background Process Management

**URL**: https://dev.to/mrvi0/the-python-developers-guide-to-background-process-management-1f6c

### Excerpts

**Systemd service for Python bot**:
```ini
[Unit]
Description=My Python Bot Service
After=network.target

[Service]
Type=idle
Restart=always
RestartSec=3
User=myuser
WorkingDirectory=/home/myuser/bot
ExecStart=/home/myuser/bot/venv/bin/python /home/myuser/bot/my_bot.py
Environment=PATH=/home/myuser/bot/venv/bin

[Install]
WantedBy=multi-user.target
```

Screen: "creates persistent terminal sessions that survive SSH disconnections"
Limitation of Screen: "No automatic restart on crashes," "Manual process management," "Sessions can be lost on server reboot"

### Takeaways

- `Type=idle` delays start until all other jobs dispatched (good for low-priority bots)
- `ExecStart` points directly to venv Python binary (no `source activate` needed)
- `WorkingDirectory` sets cwd for the service
- Screen/tmux: development only, no crash recovery

---

## Source 16: ege.dev — Systemd vs Supervisor

**URL**: https://ege.dev/posts/systemd-vs-supervisor/

### Excerpts

**Supervisor config**:
```ini
[program:foo]
command=/home/foo/bin/start_foo
user=foo
environment=LANG=en_US.UTF-8,LC_ALL=en_US.UTF-8
```

**Systemd config**:
```ini
[Unit]
Description="Foo web application"
After=network.target

[Service]
User=foo
Group=foo
Environment=LANG=en_US.UTF-8,LC_ALL=en_US.UTF-8
ExecStart=/home/foo/bin/start_foo
```

> "With `systemd` I can have the same behavior by adding `Restart=always` to `[Service]` section."

Supervisor: "controlling services with a web interface" (supervisorctl web UI)

Systemd uses targets and `Wants` declarations: "services listed in `Wants` starts when target starts, but if one of them fails it won't affect the target."

### Takeaways

- Configuration syntax nearly identical between the two
- Supervisor advantage: web UI for monitoring
- systemd advantage: pre-installed, no extra dependency, cgroup integration
- systemd `Wants` vs Supervisor groups: both handle service dependencies

---

## Source 17: ilylabs — Run Python App as systemd Service

**URL**: https://ilylabs.com/posts/python-systemd/

### Excerpts

```ini
[Unit]
Description=Dummy Service
Wants=network.target
After=network.target

[Service]
ExecStartPre=/bin/sleep 10
ExecStart=/home/dietpi/Temp/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

> "All the paths in your scripts have to be absolute paths, there can be no relative path in your scripts."

> `ExecStartPre=/bin/sleep 10` delays startup to wait for network availability.

> `Restart=always` ensures "systemd to always restart the script if it were to ever fail."

### Takeaways

- `ExecStartPre` for pre-start delays (network readiness, dependency warmup)
- Absolute paths mandatory in systemd service files
- Shebang line in Python script can point to venv: `#!/path/to/venv/bin/python3`

---

## Source 18: Galaxy Project — Controlling Galaxy with systemd or Supervisor

**URL**: https://training.galaxyproject.org/training-material/topics/admin/tutorials/systemd-supervisor/slides-plain.html

### Excerpts

systemd: "The current Linux init system" replaces init.d, rc, service, Upstart, update-rc.d

Supervisor: "A process manager written in Python" with `supervisord` daemon and `supervisorctl` CLI

Both use "INI config format"

systemd manages processes through cgroups, enforces resource limits (e.g., "MemoryLimit=32G")

> "If you prefer, you can use Supervisor to manage the Galaxy processes. The OS needs to ensure the Supervisor daemon is running, and probably manages it with systemd"

### Takeaways

- Supervisor itself needs to be managed by systemd (turtles all the way down)
- systemd has native cgroup integration for resource limits
- Both use INI-style config — migration between them is straightforward

---

## Summary & Consolidated Takeaways

### 1. Watchdog / Heartbeat Pattern

| Aspect | Best Practice |
|--------|--------------|
| **Mechanism** | Monitored process writes heartbeat (file timestamp, UDP packet, or sd_notify socket) |
| **Interval** | Ping at half the timeout interval (e.g., WatchdogSec=30s -> ping every 15s) |
| **Grace period** | Allow startup delay before checking heartbeats (`heartbeat_delay`, `ExecStartPre`) |
| **Failure action** | SIGTERM first, wait for graceful shutdown, then SIGKILL |
| **Safety margin** | Ping at `period - epsilon` to avoid racing the deadline |

### 2. Crash Loop Protection

| Approach | Implementation | Cap |
|----------|---------------|-----|
| **systemd** | `StartLimitIntervalSec=60s` + `StartLimitBurst=5` | Enters failed state, manual intervention |
| **Kubernetes** | Exponential backoff 10s -> 20s -> 40s -> ... | 5-minute maximum |
| **Bash (custom)** | Counter + time window; cooldown period if threshold exceeded | Configurable |
| **Exponential backoff** | `sleep $(( timeout * 2 ))` per attempt | Should have a maximum cap |

### 3. Process Supervision Tier List

| Tier | Tool | When to Use |
|------|------|-------------|
| **Production (Linux)** | systemd | Standard Linux server, single-process service, needs boot survival |
| **Production (Multi-process)** | Supervisor | Multiple processes in one config, web UI monitoring |
| **Production (Containers)** | Docker + restart policy | Containerized workloads |
| **Development / WSL2** | Bash wrapper (run.sh) | No systemd available, simple process management |
| **Prototype** | `until` loop / `nohup` | Quick experiments, no reliability requirements |

### 4. Bash Wrapper Best Practices (When systemd is Unavailable)

Based on all sources, a production-quality bash wrapper should include:

1. **Restart loop**: `while true; do ... done` (not `until`, which stops on success)
2. **Crash counting**: Track crashes within a time window
3. **Cooldown / backoff**: Exponential or fixed delay between restarts (prevent tight loops)
4. **Crash loop breaker**: If N crashes in M seconds, enter cooldown period (don't restart indefinitely)
5. **Network check before restart**: Verify connectivity to avoid pointless restarts during outages
6. **Signal forwarding**: Trap SIGTERM/SIGINT and forward to child process for graceful shutdown
7. **Heartbeat file**: Child writes timestamp; wrapper checks staleness and kills hung processes
8. **PID file management**: Track child PID for targeted signal delivery
9. **Logging**: Timestamp each restart event with reason

### 5. systemd vs Bash Wrapper Decision Matrix

| Factor | systemd | Bash Wrapper |
|--------|---------|-------------|
| Boot survival | Native | Requires cron @reboot or manual start |
| Heartbeat/watchdog | WatchdogSec + sd_notify | Custom file-based heartbeat |
| Crash loop protection | StartLimitBurst/Interval | Custom counter logic |
| Graceful shutdown | TimeoutStopSec + KillMode | Manual trap + wait |
| Resource limits | MemoryMax, CPUQuota | None (requires cgroups manually) |
| Logging | journald integration | Custom log files |
| WSL2 compatibility | Not available | Full support |
| Complexity | Declarative (config file) | Imperative (script logic) |
| Signal handling | Automatic (KillMode) | Manual (trap + forward) |

### 6. Key Numbers (Industry Defaults)

| Parameter | Typical Value | Source |
|-----------|--------------|-------|
| Heartbeat interval | 10-30 seconds | watchdogd, systemd WatchdogSec |
| Restart delay (transient) | 2-5 seconds | OneUptime, systemd RestartSec |
| Restart delay (init failure) | 10-30 seconds | OneUptime |
| Crash loop threshold | 5 restarts in 60-120s | systemd StartLimitBurst |
| Crash loop cooldown | 300 seconds (5 min) | Kubernetes CrashLoopBackOff max |
| Graceful shutdown timeout | 30 seconds | systemd TimeoutStopSec |
| Backoff multiplier | 2x (doubling) | Industry standard |
| Backoff cap | 5 minutes | Kubernetes |

---

## Sources Index

1. [watchdogd — Advanced System Monitor](https://github.com/troglobit/watchdogd)
2. [processWatchdog — Linux Process Monitor](https://github.com/diffstorm/processWatchdog)
3. [Squash.io — Watchdog Process in Linux](https://www.squash.io/using-a-watchdog-process-to-trigger-bash-scripts-in-linux/)
4. [Paepper.com — Bash Restart on Crash](https://www.paepper.com/blog/posts/bash-keep-script-running-restart-on-crash/)
5. [Baeldung — Keep Programs Alive](https://www.baeldung.com/linux/process-continuous-running-after-crash-reboot)
6. [TechMint — Restart Programs After Crash](https://www.tecmint.com/linux-process-running-after-crash-reboot/)
7. [TechMint — Auto Restart Service](https://www.tecmint.com/automatically-restart-service-linux/)
8. [OneUptime — systemd RestartSec and WatchdogSec (2026)](https://oneuptime.com/blog/post/2026-03-02-configure-systemd-restartsec-watchdogsec-ubuntu/view)
9. [Spindel's Gist — systemd Watchdog in Python](https://gist.github.com/Spindel/1d07533ef94a4589d348)
10. [stigok.com — sd_notify Watchdog Python 3](https://blog.stigok.com/2020/01/26/sd-notify-systemd-watchdog-python-3.html)
11. [Coderwall — Exponential Backoff in Bash](https://coderwall.com/p/--eiqg/exponential-backoff-in-bash)
12. [GitHub Gist — Bash Retry with Quadratic Backoff](https://gist.github.com/28611bfaa2395072119464521d48729a)
13. [Medium — 12 Bash Scripts for Retry & Recovery](https://medium.com/@obaff/12-bash-scripts-to-implement-intelligent-retry-backoff-error-recovery-a02ab682baae)
14. [Google Cloud — CrashLoopBackOff](https://docs.cloud.google.com/kubernetes-engine/docs/troubleshooting/crashloopbackoff-events)
15. [DEV.to — Python Background Process Management](https://dev.to/mrvi0/the-python-developers-guide-to-background-process-management-1f6c)
16. [ege.dev — Systemd vs Supervisor](https://ege.dev/posts/systemd-vs-supervisor/)
17. [ilylabs — Python systemd Service](https://ilylabs.com/posts/python-systemd/)
18. [Galaxy Project — systemd or Supervisor](https://training.galaxyproject.org/training-material/topics/admin/tutorials/systemd-supervisor/slides-plain.html)
19. [DigitalOcean — Bash Script to Restart Programs](https://www.digitalocean.com/community/tutorials/how-to-write-a-bash-script-to-restart-server-programs)
20. [systemd-watchdog PyPI](https://pypi.org/project/systemd-watchdog/)
