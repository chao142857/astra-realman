"""Explicit, bounded official SAM3 download with a token read from a no-echo TTY.

No credential files, CLI login, SDK hardware imports, or model inference. A
partial file can be resumed; only the pinned size and SHA promote it to sam3.pt.
Redirect URLs and authentication values are never printed or saved.
"""
import argparse
import datetime
import getpass
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
REPO = "facebook/sam3"
REVISION = "3c879f39826c281e95690f02c7821c4de09afae7"
SIZE = 3450062241
SHA = "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / ".cache/weights")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--proxy", help="Optional existing loopback HTTP proxy")
    parser.add_argument("--bulk-direct", action="store_true",
                        help="Use direct CDN only after two bounded successful probes")
    parser.add_argument("--max-mib-s", type=float, default=4.0)
    args = parser.parse_args()
    directory = args.directory.resolve()
    report = args.report.resolve()
    directory.relative_to(ROOT)
    report.relative_to(ROOT)
    if report.exists():
        parser.error("NEW_REPORT_REQUIRED")
    if args.max_mib_s <= 0:
        parser.error("POSITIVE_RATE_REQUIRED")
    if args.proxy:
        proxy = urlparse(args.proxy)
        if proxy.scheme != "http" or proxy.hostname not in {"127.0.0.1", "::1"} or proxy.username or proxy.password:
            parser.error("ONLY_EXISTING_LOOPBACK_HTTP_PROXY_ALLOWED")
    if args.bulk_direct:
        proof = json.loads((ROOT / "evidence/cdn-route-probe.json").read_text())
        tests = proof.get("direct_tests", [])
        if not args.proxy or proof.get("cdn_hostname") != "us.aws.cdn.hf.co" or len(tests) != 2 or not all(
            x.get("status") == 206 and x.get("bytes_read") == 1024
            and x.get("content_range") == f"bytes 0-1023/{SIZE}" for x in tests
        ):
            parser.error("TWO_VERIFIED_DIRECT_CDN_PROBES_REQUIRED")
    directory.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    target = directory / "sam3.pt"
    partial = directory / "sam3.pt.partial"
    result = {"timestamp": datetime.datetime.now().astimezone().isoformat(),
              "repo": REPO, "revision": REVISION, "expected_bytes": SIZE,
              "expected_sha256": SHA, "path": str(target), "status": "FAILED",
              "token_persisted": False, "hardware_actions": 0,
              "route": "proxy_metadata_verified_direct_cdn" if args.bulk_direct else
                       ("explicit_existing_loopback_proxy" if args.proxy else "direct"),
              "max_mib_s": args.max_mib_s}
    started = time.monotonic()
    try:
        if target.exists():
            if target.stat().st_size != SIZE or digest(target) != SHA:
                raise RuntimeError("EXISTING_CHECKPOINT_MISMATCH_PRESERVED")
            result.update(status="VERIFIED_EXISTING_OFFICIAL_CHECKPOINT", bytes=SIZE, sha256=SHA)
            return 0
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > SIZE:
            raise RuntimeError("PARTIAL_OVERSIZE_PRESERVED")
        if offset < SIZE:
            token = getpass.getpass("HF access token (memory only): ").strip()
            if not token:
                raise RuntimeError("EXPLICIT_TOKEN_REQUIRED")
            headers = {"Authorization": "Bearer " + token, "Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            session = requests.Session()
            session.trust_env = False
            bulk_session = None
            if args.proxy:
                session.proxies.update(http=args.proxy, https=args.proxy)
            transfer_start = last_progress = time.monotonic()
            downloaded = 0
            try:
                url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/sam3.pt"
                # requests strips Authorization on cross-origin redirects; TLS stays enabled.
                if args.bulk_direct:
                    resolve = session.head(url, headers=headers, allow_redirects=False, timeout=(20, 20))
                    location = resolve.headers.get("Location", "")
                    parsed = urlparse(location)
                    if resolve.status_code != 302 or parsed.scheme != "https" or parsed.hostname != "us.aws.cdn.hf.co":
                        raise RuntimeError("VERIFIED_CDN_REDIRECT_REQUIRED")
                    bulk_session = requests.Session()
                    bulk_session.trust_env = False
                    # Signed official redirect authenticates this request. The HF
                    # bearer token is never sent to the CDN or stored on disk.
                    bulk_headers = {k: v for k, v in headers.items() if k != "Authorization"}
                    response = bulk_session.get(location, headers=bulk_headers, stream=True,
                                                allow_redirects=False, timeout=(20, 45))
                    result["bulk_hostname"] = parsed.hostname
                else:
                    response = session.get(url, headers=headers, stream=True, timeout=(20, 45))
                with response:
                    result["http_status"] = response.status_code
                    result["redirect_count"] = len(response.history) + int(args.bulk_direct)
                    if response.status_code not in {200, 206}:
                        raise RuntimeError(f"OFFICIAL_DOWNLOAD_HTTP_{response.status_code}")
                    content_range = response.headers.get("Content-Range", "")
                    if offset and (response.status_code != 206 or not content_range.startswith(f"bytes {offset}-")):
                        raise RuntimeError("RESUME_RANGE_NOT_HONORED_PARTIAL_PRESERVED")
                    with partial.open("ab" if offset else "wb") as stream:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            if stream.tell() + len(chunk) > SIZE:
                                raise RuntimeError("OFFICIAL_DOWNLOAD_EXCEEDS_PINNED_SIZE")
                            stream.write(chunk)
                            downloaded += len(chunk)
                            elapsed = time.monotonic() - transfer_start
                            delay = downloaded / (args.max_mib_s * 1024**2) - elapsed
                            if delay > 0:
                                time.sleep(min(delay, 1))
                            if time.monotonic() - last_progress >= 20:
                                print(json.dumps({"downloaded_bytes": offset + downloaded,
                                                  "total_bytes": SIZE,
                                                  "percent": round(100 * (offset + downloaded) / SIZE, 2)}), flush=True)
                                last_progress = time.monotonic()
                result.update(resumed_from_bytes=offset, transferred_bytes=downloaded,
                              transfer_elapsed_s=time.monotonic() - transfer_start)
            finally:
                session.close()
                if bulk_session is not None:
                    bulk_session.close()
                headers.clear()
                token = None
        actual_size = partial.stat().st_size
        if actual_size != SIZE:
            raise RuntimeError("OFFICIAL_DOWNLOAD_SIZE_MISMATCH_PARTIAL_PRESERVED")
        actual_sha = digest(partial)
        result.update(bytes=actual_size, sha256=actual_sha)
        if actual_sha != SHA:
            raise RuntimeError("OFFICIAL_DOWNLOAD_SHA_MISMATCH_PARTIAL_PRESERVED")
        partial.rename(target)
        result["status"] = "VERIFIED_OFFICIAL_CHECKPOINT"
        return 0
    except Exception as exc:
        # Do not serialize request exceptions: their URL may carry signed CDN data.
        result["error_type"] = type(exc).__name__
        if isinstance(exc, RuntimeError):
            result["error_code"] = str(exc)
        result["partial_bytes"] = partial.stat().st_size if partial.exists() else 0
        return 1
    finally:
        result["elapsed_s"] = time.monotonic() - started
        report.write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
