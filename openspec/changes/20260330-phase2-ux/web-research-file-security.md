# Web Research: Secure File Download in Slack Bots (SSRF Prevention & Temp File Management)

**Date**: 2026-03-30
**Keywords searched**:
1. "Slack bot file download SSRF prevention best practices"
2. "Python urllib SSRF mitigation url validation 2025 2026"
3. "temp file management cleanup security Python bot"

---

## Source 1: OWASP Server Side Request Forgery Prevention Cheat Sheet

**URL**: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

### Excerpts

> "apply the allowlist approach when input validation is used because, most of the time, the format of the information expected from the user is globally known."

> "Do not accept complete URLs from the user because URLs are difficult to validate and the parser can be abused."

> "Disable the support for the following of redirection in your web client."

**Case 2 (any external URL) validation flow:**
1. Input validation using verified libraries
2. Block-list approach verifying IPs are public
3. For domains: resolve against internal-only DNS; if it resolves, reject it
4. Retrieve all A + AAAA records; validate all resulting IPs are public
5. Restrict protocol to allowlist (HTTP/HTTPS only)

**Minimum deny-list (last resort):**
- AWS IMDS: `169.254.169.254`, `metadata.amazonaws.com`
- GCP Metadata: `metadata.google.internal`, `169.254.169.254`
- Azure IMDS: `169.254.169.254`
- Localhost: `127.0.0.0/8`, `0.0.0.0/8`, `::1/128`
- RFC1918: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- Multicast: `224.0.0.0/4`, `ff00::/8`

> "Deny-lists are bypass-prone. Prefer allow-lists."

### Takeaways
- Allowlist approach is always preferred over blocklist
- Never accept raw user URLs if possible; accept components (domain, path) and construct URLs server-side
- Disable HTTP redirect following; if redirects are needed, re-validate every hop
- Resolve DNS and validate ALL resulting IPs (A + AAAA) before connecting
- Cloud metadata endpoints (169.254.169.254) must always be blocked

---

## Source 2: Include Security - Mitigating SSRF in 2023

**URL**: https://blog.includesecurity.com/2023/03/mitigating-ssrf-in-2023/

### Excerpts

> "DNS rebinding is an even more devastating technique. It exploits the TOCTTOU that exists between the DNS resolution of a domain when it's validated, and when the request is actually made."

> "A redirect is the most straightforward way to demonstrate the problem of TOCTTOU in the context of HTTP."

> "The BASE_URL becomes HTTP basic authentication credentials due to use of '@', and 'png' becomes a URL fragment due to use of '#'."

> "it's hard to design perfect blocklists and possible for libraries to miss some detail of address validation -- this is particularly evident with IPv6 support"

**Recommended solution -- Stripe Smokescreen CONNECT proxy:**
> "It is deployed on your network, where it proxies HTTP traffic between the application and the destination URL and has rules about which hosts it allows to talk to"

### Takeaways
- TOCTOU (Time-of-Check to Time-of-Use) is the fundamental SSRF problem: DNS can resolve differently between validation and actual connection
- URL parser differentials (e.g., `@` treated as basic auth, `#` as fragment) enable bypass of naive allowlists
- IPv6 representations (`[::]`, `::1`, hex/octal/dword encoding of IPs) make blocklists fragile
- Infrastructure-level solution (CONNECT proxy like Smokescreen) eliminates TOCTOU by validating IP at socket-connect time
- For application-level defense, pin DNS resolution: resolve once, then connect to the resolved IP with Host header set explicitly

---

## Source 3: Pydantic-AI SSRF Vulnerability (CVE-2026-25580, GHSA-2jrp-274c-jhv3)

**URL**: https://github.com/pydantic/pydantic-ai/security/advisories/GHSA-2jrp-274c-jhv3

### Excerpts

> "A Server-Side Request Forgery (SSRF) vulnerability exists in Pydantic AI's URL download functionality."

> The `download_item()` helper function "downloads content from URLs without validating that the target is a public internet address."

**Attack vectors:**
1. Access internal services by targeting localhost or private IP ranges (10.x.x.x, 172.16.x.x, 192.168.x.x)
2. Steal cloud credentials via metadata endpoints like AWS IMDSv1 at 169.254.169.254
3. Enumerate internal networks to discover hosts and services

**Fix in v1.56.0:**
> DNS resolution before requests, private IP blocking, and cloud metadata endpoint restrictions.

> "Cloud metadata endpoints...are **always blocked**, even with `allow-local`."

### Takeaways
- Real-world 2026 CVE (CVSS 8.6) in a popular Python AI framework -- identical pattern to Slack bot file download
- The vulnerable function simply downloaded URLs from user-supplied message history without validation
- Fix implemented: DNS pre-resolution + private IP blocking + unconditional cloud metadata blocking
- Even when `allow-local` is explicitly enabled, cloud metadata must remain blocked -- defense in depth

---

## Source 4: AutoGPT SSRF via DNS Rebinding (CVE-2025-31490, GHSA-wvjg-9879-3m7w)

**URL**: https://github.com/Significant-Gravitas/AutoGPT/security/advisories/GHSA-wvjg-9879-3m7w

### Excerpts

> The `validate_url()` function performs initial DNS resolution that returns a non-blocked IP address. However, because the DNS response has a TTL of 0, subsequent resolution attempts can return a different IP -- potentially one in a blocked range.

> "A simple resolution returns 1.2.3.4, but the exact same query moments later returns 169.254.169.254" with TTL set to 0.

> The wrapper "disables redirects for the initial request, then manually re-requests using the new location." During this manual re-request, the code fails to strip security-sensitive headers like `Authorization` and `Proxy-Authorization` headers, along with cookies.

**Mitigation:**
> Replacing the hostname with a validated IP address while setting the `Host` header explicitly, preventing DNS re-resolution during the actual HTTP request.

### Takeaways
- DNS rebinding with TTL=0 is a practical attack -- attacker alternates resolution between safe IP and internal IP
- After validation, connect to the **resolved IP** (not hostname) to prevent re-resolution
- Set `Host` header explicitly when connecting to IP to maintain HTTP semantics
- When handling redirects manually, strip `Authorization`, `Proxy-Authorization`, and cookies on cross-origin redirects
- CVSS 7.5 (High) -- credential leakage through auth header forwarding is a serious secondary risk

---

## Source 5: WeasyPrint SSRF Protection Bypass (CVE-2025-68616)

**URL**: https://www.sentinelone.com/vulnerability-database/cve-2025-68616/

### Excerpts

> "urllib automatically follows HTTP redirects (301, 302, etc.) without invoking the developer's security checks on the redirect destination."

> "The root cause is the automatic redirect-following behavior in Python's urllib library combined with insufficient re-validation of redirect destinations."

**Patch approach:**
> The patch disables HTTP redirects in the deprecated `default_url_fetcher` function and provides a secure URLFetcher class that validates all URLs in redirect chains against configured policies.

### Takeaways
- Python's urllib follows redirects automatically and silently -- security checks on the initial URL are bypassed for redirect targets
- Any code using urllib (or requests with `allow_redirects=True`) to fetch user-supplied URLs is vulnerable
- Fix: either disable redirects entirely (`allow_redirects=False`) or implement a custom redirect handler that re-validates each hop
- This is the same TOCTOU pattern -- validation happens before the redirect, connection happens after

---

## Source 6: Sourcery - SSRF Prevention Code Patterns for Python

**URL**: https://www.sourcery.ai/vulnerabilities/python-flask-security-injection-ssrf-requests

### Excerpts

**URL Validation Function:**
```python
def validate_url_for_ssrf(url):
    """Validate URL against SSRF attacks"""
    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError('Invalid URL format')

    if parsed.scheme not in ['http', 'https']:
        raise ValueError('Only HTTP and HTTPS protocols are allowed')

    if not parsed.hostname:
        raise ValueError('URL must have a valid hostname')

    if not is_allowed_domain(parsed.hostname):
        raise ValueError('Domain not allowed')

    check_internal_network_access(parsed.hostname)
    return url
```

**IP Address Validation:**
```python
def check_internal_network_access(hostname):
    """Prevent access to internal networks"""
    try:
        ip = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip)

        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
            raise ValueError('Requests to internal networks are not allowed')

        dangerous_ranges = [
            ipaddress.ip_network('169.254.0.0/16'),  # AWS metadata
            ipaddress.ip_network('10.0.0.0/8'),
            ipaddress.ip_network('172.16.0.0/12'),
            ipaddress.ip_network('192.168.0.0/16')
        ]
        for network in dangerous_ranges:
            if ip_obj in network:
                raise ValueError('IP address not allowed')
    except socket.gaierror:
        raise ValueError('Unable to resolve hostname')
```

**Safe Request with Redirect Handling:**
```python
def make_safe_request(url, method='GET', **kwargs):
    """Make a safe HTTP request with proper configurations"""
    safe_kwargs = {
        'timeout': app.config['REQUEST_TIMEOUT'],
        'allow_redirects': False,  # Prevent redirect SSRF
        'stream': True,
        'headers': kwargs.get('headers', {})
    }
    safe_kwargs['headers']['User-Agent'] = 'SafeFlaskApp/1.0'

    response = requests.get(url, **safe_kwargs)

    content_length = response.headers.get('content-length')
    if content_length and int(content_length) > app.config['MAX_REQUEST_SIZE']:
        raise ValueError('Response too large')

    return response
```

**Domain Allowlist Checking:**
```python
def is_allowed_domain(hostname):
    """Check if domain is in allowlist"""
    allowed_domains = app.config['ALLOWED_DOMAINS']
    for domain in allowed_domains:
        if hostname == domain or hostname.endswith('.' + domain):
            return True
    return False
```

### Takeaways
- Complete defense-in-depth pattern: scheme check -> hostname allowlist -> DNS resolve -> IP blocklist -> disable redirects -> size limit
- `ipaddress.ip_address().is_private` covers most RFC1918 ranges; add explicit check for `169.254.0.0/16` (link-local / cloud metadata)
- `allow_redirects=False` is critical when using `requests` library
- `stream=True` + content-length check prevents memory exhaustion before downloading body
- Always set explicit timeout

---

## Source 7: Slack Developer Docs - Security Best Practices

**URL**: https://docs.slack.dev/tools/deno-slack-sdk/guides/following-security-best-practices/

### Excerpts

> "Slack's `outgoingDomains` configuration limits which domains your custom function code can use when making external network requests."

> "Functions are given a short-lived token that can be used to make Slack API calls, which use the scopes requested in the app's manifest."

> "Only request the scopes your functions need to do their job."

### Takeaways
- Slack's own platform uses domain allowlisting for egress (`outgoingDomains`)
- Token scope minimization: only request `files:read` / `files:write` as needed
- Short-lived tokens reduce blast radius of token theft

---

## Source 8: Slack Developer Docs - Working with Files

**URL**: https://docs.slack.dev/messaging/working-with-files/

### Excerpts

File objects have two download URLs:
- **`url_private`**: `https://files.slack.com/files-pri/T0123ABCD4E-FF012AB3CDE4/hello.txt`
- **`url_private_download`**: `https://files.slack.com/files-pri/T0123ABCD4E-F012AB3CDE4/download/hello.txt`

> "When a user uploads a file, Slack will scan the file for malware before making it available in the workspace."

File objects contain metadata: `id, created, timestamp, name, title, mimetype, filetype, pretty_type, user, user_team, editable, size, mode, is_external, external_type, is_public`.

### Takeaways
- Slack file URLs are always under `files.slack.com` -- safe to allowlist this domain for download
- `url_private_download` requires Bot Token (`Authorization: Bearer xoxb-...`) in request header
- Slack performs server-side malware scanning, but bots should still validate mimetype/size before processing
- File metadata includes `size` and `mimetype` -- validate these before downloading to prevent resource exhaustion

---

## Source 9: OpenStack - Using Temporary Files Securely

**URL**: https://security.openstack.org/guidelines/dg_using-temporary-files-securely.html

### Excerpts

> "Malicious users that can predict the file name and write to directory containing the temporary file can effectively hijack the temporary file by creating a symlink with the name of the temporary file before the file is created by the program."

> "TemporaryFile should be used whenever possible. Besides creating temporary files safely it also hides the file and cleans up the file automatically."

**Safe functions:**
- `tempfile.TemporaryFile`
- `tempfile.NamedTemporaryFile`
- `tempfile.SpoolTemporaryFile`
- `tempfile.mkdtemp`

**Unsafe functions to avoid:**
- `tempfile.mktemp` (race condition)
- `open()` with manually constructed paths

> "Ensure the file is read/write by the creator only" using `os.umask(0077)` before file creation.

> "Temporary files should always be created on the local filesystem. Many remote filesystems (for example, NFSv2) do not support the open flags needed to safely create temporary files."

### Takeaways
- Never use `tempfile.mktemp()` -- it has a race condition between name generation and file creation
- Use `tempfile.NamedTemporaryFile` or `tempfile.mkdtemp()` for files that need a visible path (e.g., passing to subprocess)
- Context manager (`with` statement) guarantees cleanup even on exceptions
- Set restrictive permissions (`0o600` for files, `0o700` for directories) -- especially important in `/tmp` shared directories
- Use local filesystem only for temp files, not NFS/network mounts

---

## Source 10: Python tempfile Module Documentation

**URL**: https://docs.python.org/3/library/tempfile.html

### Excerpts

> `mkstemp()` "creates a temporary file in the most secure manner possible. There are no race conditions in the file's creation, assuming that the platform properly implements the `os.O_EXCL` flag for `os.open()`."

> `NamedTemporaryFile`: "If delete is true (the default), the file is created in a secure fashion and will be automatically deleted as soon as it is closed."

> "Files names used by this module include a string of random characters which allows those files to be securely created in shared temporary directories."

### Takeaways
- `mkstemp()` uses `O_EXCL` flag -- atomic file creation, no race condition
- `NamedTemporaryFile(delete=True)` is the default and preferred -- auto-cleanup on close
- Use `delete=False` only when file must outlive the context manager (e.g., passing path to external process), and ensure manual cleanup in `finally` block
- Random characters in filenames prevent prediction-based attacks
- `SpooledTemporaryFile(max_size=N)` keeps small files in memory, spills to disk when exceeding threshold -- useful for file content validation before writing

---

## Source 11: RedVeil.ai - Preventing SSRF Vulnerabilities

**URL**: https://www.redveil.ai/additional-resources/vulnerabilities/preventing-ssrf-vulnerabilities

### Excerpts

**Blocked IP ranges:**
- `10.0.0.0/8`
- `172.16.0.0/12`
- `192.168.0.0/16`
- `127.0.0.0/8`
- `169.254.0.0/16` (cloud metadata and link-local)
- `0.0.0.0/8`

**Cloud metadata protection:**
> Enforcing IMDSv2 "requires a session token, providing protection against SSRF."

**Content validation:**
> Validate the `Content-Type` header matches expectations and implement size limits to prevent resource exhaustion.

**Network architecture:**
> Implementing network segmentation so application servers cannot reach sensitive internal services.

### Takeaways
- `0.0.0.0/8` should be blocked (often overlooked) -- `0.0.0.0` can map to localhost on some systems
- Content-Type validation prevents processing unexpected file types (e.g., HTML served as image)
- Size limits at both header-check and actual-download stages prevent resource exhaustion
- Network segmentation is defense-in-depth even when application-layer checks are in place

---

## Source 12: Stripe Smokescreen

**URL**: https://github.com/stripe/smokescreen

### Excerpts

> Smokescreen is "a HTTP CONNECT proxy that proxies most traffic from Stripe to the external world (e.g., webhooks)."

> "It uses a pre-configured hostname ACL to only allow requests addressed to certain allow-listed hostnames, to ensure that no malicious code is attempting to make requests to unexpected services."

> "It also resolves each domain name that is requested, and ensures that it is a publicly routable IP address and not an internal IP address."

> Clients contact Smokescreen over mTLS. Upon receiving a connection, Smokescreen "authenticates the client's certificate against a configurable set of CAs and CRLs, extracts the client's identity, and checks the client's requested CONNECT destination against a configurable per-client ACL."

### Takeaways
- Gold standard infrastructure-level SSRF prevention: resolves DNS and validates IP at the proxy level (eliminates TOCTOU)
- Per-client ACL allows fine-grained egress control (different services have different allowed destinations)
- mTLS for client authentication -- not applicable to simple bot deployments, but the architecture pattern is instructive
- For a Slack bot, the equivalent is: resolve DNS before connecting, validate the resolved IP, then connect to the IP directly

---

## Source 13: Snyk - Secure Python URL Validation

**URL**: https://snyk.io/blog/secure-python-url-validation/

### Excerpts

**`validators` package -- public IP detection:**
```python
import validators

validation = validators.url("https://10.0.0.1", public=True)
if validation:
    print("URL is valid")
else:
    print("URL is invalid")
```

> The `public=True` parameter rejects internal IP addresses, helpful for preventing "server-side request forgery" attacks.

**urllib approach:**
```python
from urllib.parse import urlparse
result = urlparse("https://www.example.com")
if result.scheme and result.netloc:
    print("Success")
```

### Takeaways
- `validators.url(url, public=True)` is a quick first-pass check but should not be sole defense (doesn't handle DNS rebinding)
- `urlparse` alone only checks syntax, not security -- must be combined with IP resolution checks
- Regex-based URL validation is fragile and hard to maintain -- prefer library-based validation

---

## Source 14: Python atexit & Signal Handling for Temp Cleanup

**URL**: https://docs.python.org/3/library/atexit.html

### Excerpts

> "The functions registered via this module are not called when the program is killed by a signal not handled by Python, when a Python fatal internal error is detected, or when `os._exit()` is called."

### Takeaways
- `atexit` handlers do NOT fire on SIGKILL, unhandled signals, or `os._exit()`
- For Slack bots managed by watchdog (which sends SIGTERM then SIGKILL), temp cleanup must be:
  1. Primary: context manager (`with` statement) for immediate cleanup
  2. Secondary: SIGTERM signal handler for graceful shutdown cleanup
  3. Tertiary: periodic sweep of stale temp files (cron or in-process timer)
- Never rely solely on `atexit` for temp file cleanup in long-running processes

---

## Summary of Findings

### SSRF Prevention for Slack Bot File Downloads

**For Slack-hosted files (url_private_download):**
- Allowlist `files.slack.com` as the only permitted download domain
- Validate URL scheme is `https` only
- Validate hostname matches `files.slack.com` or `*.slack.com` after parsing
- Set explicit timeout and max file size
- Use `stream=True` and check Content-Length before reading body

**For any external URLs (if supported):**
1. Parse URL and validate scheme (`https` only)
2. Extract hostname; resolve DNS to get all IP addresses
3. Validate ALL resolved IPs: reject private, loopback, link-local, multicast, and `0.0.0.0/8`
4. Connect to the **resolved IP** (not hostname) with `Host` header set explicitly -- prevents DNS rebinding
5. Disable automatic redirects (`allow_redirects=False`); if redirects needed, re-validate each hop
6. Validate Content-Type and enforce max file size
7. Set request timeout (connect + read)
8. Strip `Authorization` headers on cross-origin redirects

**Key bypass vectors to defend against:**
- DNS rebinding (TTL=0 alternating resolution)
- HTTP redirect to internal IP
- URL parser differentials (`@`, `#`, backslash, encoding tricks)
- IPv6 representations (`[::]`, `::1`, IPv4-mapped IPv6)
- Decimal/octal/hex IP encoding (`0x7f000001` = `127.0.0.1`)

### Temp File Management for Long-Running Bot

**Creation:**
- Use `tempfile.NamedTemporaryFile(delete=True)` with context manager when possible
- Use `tempfile.mkdtemp()` for per-request directories (isolate files by thread_ts)
- Set `prefix=` to identify owning module (e.g., `prefix="slack-file-"`)
- Ensure restrictive permissions (0o600 files, 0o700 directories)

**Cleanup strategy (defense in depth):**
1. **Immediate**: context manager / `finally` block after processing
2. **Graceful shutdown**: SIGTERM handler cleans temp directory
3. **Periodic sweep**: timer-based cleanup of files older than threshold (e.g., 1 hour)
4. **Startup cleanup**: on bot restart, sweep stale temp files from previous run

**Avoid:**
- `tempfile.mktemp()` (race condition)
- Manual path construction in `/tmp` (predictable names, symlink attacks)
- `delete=False` without explicit cleanup in `finally`
- Relying solely on `atexit` (not called on SIGKILL)

### Recommended Implementation Pattern

```python
import tempfile, os, shutil, ipaddress, socket
from urllib.parse import urlparse

ALLOWED_DOWNLOAD_HOSTS = {"files.slack.com"}
BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

def validate_download_url(url: str) -> str:
    """Validate URL is safe to download from."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Only HTTPS allowed")
    if not parsed.hostname:
        raise ValueError("No hostname")
    if parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        # For non-Slack URLs, resolve and check IP
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname))
        except (socket.gaierror, ValueError):
            raise ValueError(f"Cannot resolve {parsed.hostname}")
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError("Internal IP not allowed")
        for net in BLOCKED_NETWORKS:
            if ip in net:
                raise ValueError("Blocked IP range")
    return url

def download_to_tempdir(url: str, thread_ts: str) -> str:
    """Download file to isolated temp directory."""
    validate_download_url(url)
    tmpdir = tempfile.mkdtemp(prefix=f"slack-{thread_ts}-")
    os.chmod(tmpdir, 0o700)
    try:
        resp = requests.get(url, stream=True, timeout=30,
                           allow_redirects=False,
                           headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        size = int(resp.headers.get("content-length", 0))
        if size > MAX_FILE_SIZE:
            raise ValueError("File too large")
        # ... write to file in tmpdir ...
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return tmpdir
```

---

*Research conducted 2026-03-30 using WebSearch + WebFetch.*
