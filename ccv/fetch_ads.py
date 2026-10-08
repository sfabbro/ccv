"""Fetch BibTeX from the NASA ADS API.

Endpoints:
    search  GET  https://api.adsabs.harvard.edu/v1/search/query
    export  POST https://api.adsabs.harvard.edu/v1/export/bibtex

The token comes from ADS > Settings > API Token. Provide it via the
ADS_API_TOKEN environment variable or the --token flag.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    import certifi
except ImportError:  # optional; scholarly/requests usually pull it in
    certifi = None

SEARCH_URL = "https://api.adsabs.harvard.edu/v1/search/query"
EXPORT_URL = "https://api.adsabs.harvard.edu/v1/export/bibtex"

# ADS export endpoint rejects very large payloads; chunk the bibcodes.
EXPORT_CHUNK = 400


class AdsError(RuntimeError):
    pass


_INITIALS_RE = re.compile(r"[A-Za-z]\.?(?:[ -][A-Za-z]\.?)*")


def split_ads_authors(raw: str) -> list[str]:
    """Split a comma-separated ADS author list, keeping 'Surname, Initials' together.

    'Fabbro, S'        -> ['Fabbro, S']           (one author: initials glued)
    'Fabbro, Kavelaars' -> ['Fabbro', 'Kavelaars'] (two surnames)

    A naive split(',') on 'Fabbro, S' would emit author:"S" and match
    thousands of unrelated papers.
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return []
    out = [parts[0]]
    for part in parts[1:]:
        if len(part) <= 12 and _INITIALS_RE.fullmatch(part):
            out[-1] += ", " + part
        else:
            out.append(part)
    return out


def _context() -> ssl.SSLContext:
    # Debugging aid for environments with broken CA bundles (e.g. sandboxes).
    if os.environ.get("CCV_ADS_INSECURE") == "1":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    # conda/pixi OpenSSL often points at a prefix that no longer exists after
    # the checkout moves. certifi ships a current bundle with the env.
    if certifi is not None and os.path.isfile(certifi.where()):
        return ssl.create_default_context(cafile=certifi.where())
    system = "/etc/ssl/cert.pem"
    if os.path.isfile(system):
        return ssl.create_default_context(cafile=system)
    return ssl.create_default_context()


def _request(url: str, *, token: str, payload: dict[str, Any] | None = None) -> Any:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, context=_context(), timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise AdsError(f"ADS API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise AdsError(f"ADS API unreachable: {exc.reason}") from exc


def _build_query(
    *,
    authors: list[str] | None = None,
    orcid: str | None = None,
    bibcodes: list[str] | None = None,
    query: str | None = None,
) -> str:
    if bibcodes:
        return " OR ".join(f'bibcode:"{b}"' for b in bibcodes)
    if orcid:
        return f"orcid:{orcid}"
    if authors:
        return " OR ".join(f'author:"{a}"' for a in authors)
    if query:
        return query
    raise AdsError("nothing to search for: give --author, --orcid, --bibcodes, or --query")


def fetch_bibcodes(
    token: str,
    *,
    authors: list[str] | None = None,
    orcid: str | None = None,
    bibcodes: list[str] | None = None,
    query: str | None = None,
    max_rows: int = 1000,
    since_year: int | None = None,
) -> list[str]:
    """Return the list of bibcodes matching the request, optionally year-filtered."""
    q = _build_query(
        authors=authors, orcid=orcid, bibcodes=bibcodes, query=query
    )
    docs = fetch_docs(token, q, max_rows=max_rows, since_year=since_year)
    return [doc["bibcode"] for doc in docs]


def fetch_docs(
    token: str, q: str, *, max_rows: int = 1000, since_year: int | None = None
) -> list[dict[str, Any]]:
    """Search ADS and return docs with bibcode, year, property and doctype."""
    params = urllib.parse.urlencode(
        {"q": q, "fl": "bibcode,year,property,doctype,title", "rows": max_rows,
         "sort": "date desc"}
    )
    result = _request(f"{SEARCH_URL}?{params}", token=token, payload=None)
    docs = (result.get("response") or {}).get("docs") or []
    out: list[dict[str, Any]] = []
    for doc in docs:
        if not doc.get("bibcode"):
            continue
        if since_year:
            try:
                if int(doc.get("year")) < since_year:
                    continue
            except (TypeError, ValueError):
                pass
        out.append(doc)
    return out


def annotate_bibtex(bibtex: str, docs: list[dict[str, Any]]) -> str:
    """Add ADS metadata the BibTeX export lacks: refereed flag and doctype.

    Inserts ``adsrefereed = {yes|no}`` and ``adsdoctype = {...}`` right after
    each ``@TYPE{bibcode,`` line so the CCV builder can mark preprints and
    meeting abstracts as non-refereed.
    """
    meta = {doc["bibcode"]: doc for doc in docs}

    def add(match: re.Match[str]) -> str:
        doc = meta.get(match.group(2))
        if not doc:
            return match.group(0)
        props = {str(p).upper() for p in doc.get("property") or []}
        refereed = "yes" if "REFEREED" in props else "no"
        doctype = str(doc.get("doctype") or "")
        return (f"{match.group(0)}\n      adsrefereed = {{{refereed}}},"
                f"\n      adsdoctype = {{{doctype}}},")

    # Drop earlier annotations so re-annotating never duplicates fields.
    bibtex = re.sub(r"\n\s*ads(?:refereed|doctype)\s*=\s*\{[^}]*\},", "", bibtex)
    return re.sub(r"(@\w+\{)([^,\s]+),", add, bibtex)


def lookup_titles(
    token: str, titles: list[str], surnames: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """Find ADS records for titles (e.g. Scholar-only papers) by the CV owner.

    Returns {title: doc}.  Each query requires the owner's surname so only
    records that actually list the owner come back.
    """
    found: dict[str, dict[str, Any]] = {}
    author_q = " OR ".join(f'author:"{s}"' for s in surnames if s)
    for title in titles:
        words = re.sub(r"[\"()\[\]{}:^~*?\\/\u2026]|\.\.\.", " ", title).split()
        if len(words) < 3:
            continue
        q = f'title:"{" ".join(words)}"'
        if author_q:
            q += f" ({author_q})"
        try:
            docs = fetch_docs(token, q, max_rows=5)
        except AdsError:
            continue
        # Prefer the refereed version when both the preprint and the paper exist.
        docs.sort(key=lambda d: "REFEREED" not in {str(p).upper() for p in d.get("property") or []})
        if docs:
            found[title] = docs[0]
    return found


def export_bibtex(token: str, bibcodes: list[str]) -> str:
    """Return the concatenated BibTeX for *bibcodes* via the ADS export API."""
    blocks: list[str] = []
    for start in range(0, len(bibcodes), EXPORT_CHUNK):
        chunk = bibcodes[start : start + EXPORT_CHUNK]
        payload = {"bibcode": chunk}
        result = _request(EXPORT_URL, token=token, payload=payload)
        exported = result.get("export") or ""
        if exported.strip():
            blocks.append(exported)
    return "\n".join(blocks)


def fetch_bibtex_file(
    out_path: str | Path,
    *,
    token: str | None = None,
    authors: list[str] | None = None,
    orcid: str | None = None,
    bibcodes: list[str] | None = None,
    query: str | None = None,
    max_rows: int = 1000,
    since_year: int | None = None,
) -> dict[str, Any]:
    token = token or os.environ.get("ADS_API_TOKEN")
    if not token:
        raise AdsError(
            "no ADS API token: set ADS_API_TOKEN or pass --token "
            "(ADS > Settings > API Token)"
        )
    q = _build_query(authors=authors, orcid=orcid, bibcodes=bibcodes, query=query)
    docs = fetch_docs(token, q, max_rows=max_rows, since_year=since_year)
    bibcodes_found = [doc["bibcode"] for doc in docs]
    bibtex = annotate_bibtex(export_bibtex(token, bibcodes_found), docs)
    Path(out_path).write_text(bibtex, encoding="utf-8")
    return {"bibcodes": len(bibcodes_found), "bytes": len(bibtex), "out": str(out_path)}
