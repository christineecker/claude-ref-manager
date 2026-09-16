#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:read <pmid...>` -- open the dashboard's live PDF+notes viewer
scoped to one or more already-fetched papers.

This does not render a reading reconstruction of converted text. A pmid is
only "ready" here if it has a real PDF on file (`raw/<hash>/source.pdf`,
same check as `has_pdf()` everywhere else in the library); otherwise it is
reported as `no_pdf` and the caller is pointed at `/ref:fetch-pdf` or
`/ref:attach`.

Reuses `dashboard.py`'s loopback `ThreadingHTTPServer` (token auth,
DNS-rebinding check, path allowlist, pdf.js viewer, notes API writing
through `note.py append()`) rather than a separate reader implementation --
opening `?paper=<pmid>&tab=pdf` deep-links straight into that paper's PDF
tab in the drawer instead of the library table.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import dashboard
from lib_selector import has_pdf


def render_one(library_root: Path, pmid: str) -> dict:
    paper_dir = library_root / "papers" / str(pmid)
    if not (paper_dir / "meta.json").exists():
        return {"pmid": str(pmid), "result": "failed", "reason": "no meta.json -- run /ref:add first"}
    if not has_pdf(paper_dir):
        return {"pmid": str(pmid), "result": "no_pdf", "reason": "no PDF on file -- run /ref:fetch-pdf or /ref:attach"}
    return {"pmid": str(pmid), "result": "ready"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--port", type=int, default=0, help="0 = OS-assigned ephemeral port")
    ap.add_argument("--no-open", action="store_true", help="do not open a browser tab automatically")
    ap.add_argument("pmids", nargs="+")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    exit_code = 0
    ready: list[str] = []
    for pmid in args.pmids:
        result = render_one(library_root, pmid)
        line = f"{result['pmid']}: {result['result']}"
        if result.get("reason"):
            line += f" -- {result['reason']}"
        print(line)
        if result["result"] == "ready":
            ready.append(result["pmid"])
        else:
            exit_code = 1

    if not ready:
        return exit_code

    httpd = dashboard.build_server(library_root, port=args.port)
    port = httpd.server_address[1]
    token = httpd.ref_token  # type: ignore[attr-defined]

    for pmid in ready:
        url = f"http://127.0.0.1:{port}/?token={token}&paper={pmid}&tab=pdf"
        print(f"{pmid}: {url}")
        if not args.no_open:
            webbrowser.open(url)

    print(f"reader serving at http://127.0.0.1:{port}/ (Ctrl-C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
