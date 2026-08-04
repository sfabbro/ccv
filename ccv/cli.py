"""Command-line interface for building CCV XML files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import xmlutil
from .builder import build_from_base
from .validate import discovery_metrics, summarize_tree, validate_publications


def _cmd_build(args: argparse.Namespace) -> int:
    surnames = tuple(s.strip() for s in args.author_surname.split(",") if s.strip())
    result = build_from_base(
        args.base,
        args.bib,
        args.out,
        author_surnames=surnames or ("Fabbro",),
        since=args.since,
        last_years=args.last_years,
        assign_record_ids=args.assign_record_ids,
        overrides=args.overrides,
        preserve_extra=args.preserve_extra,
        verbose=args.verbose,
    )
    counts = result["publication_counts"]
    total = sum(counts.values())
    print(f"Wrote {result['written']}")
    print(f"BibTeX entries read: {result['bib_entries']}")
    print(f"Publications written: {total}")
    for label, n in counts.items():
        print(f"  {label}: {n}")
    changes = (
        f"added {len(result['added'])}, updated {len(result['updated'])}"
    )
    if args.preserve_extra:
        changes += f", kept {len(result['kept'])}"
    changes += f", removed {len(result['removed'])}"
    print(f"Changes: {changes}")
    if result["duplicates"]:
        print(f"Duplicates dropped: {len(result['duplicates'])}")
    if args.verbose:
        for key, reason in result["skipped"]:
            print(f"  skip: {key}: {reason}")
        for key in result["removed"]:
            print(f"  removed: {key}")
        for key in result["added"]:
            print(f"  added: {key}")
        for key in result["updated"]:
            print(f"  updated: {key}")
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    tree = xmlutil.load_ccv(args.base)
    summary = summarize_tree(tree)
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0
    print(f"CCV: {args.base}")
    for key in sorted(summary):
        if key.startswith("_"):
            continue
        print(f"  {summary[key]:4d}  {key}")
    print("Discovery metrics:")
    for key, value in sorted(discovery_metrics(tree).items()):
        if isinstance(value, dict):
            continue
        print(f"  {value!s:>6}  {key}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    tree = xmlutil.load_ccv(args.base)
    issues = validate_publications(tree)
    if not issues:
        print(f"{args.base}: no issues found in the Publications section")
        return 0
    print(f"{args.base}: {len(issues)} issue(s) found:")
    for issue in issues:
        print(f"  [{issue['label']}] {issue['message']}")
    if args.strict:
        return 1
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    from .fetch_ads import AdsError, fetch_bibtex_file, split_ads_authors

    authors = split_ads_authors(args.author) if args.author else None
    if args.author and not authors:
        print(f"error: --author {args.author!r} contains no names", file=sys.stderr)
        return 1
    bibcodes = [b.strip() for b in args.bibcodes.split(",") if b.strip()] if args.bibcodes else None
    try:
        info = fetch_bibtex_file(
            args.out,
            token=args.token,
            authors=authors,
            orcid=args.orcid,
            bibcodes=bibcodes,
            query=args.query,
            max_rows=args.max,
            since_year=args.since_year,
        )
    except AdsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {info['out']}: {info['bibcodes']} papers, {info['bytes']} bytes")
    if info["bibcodes"] == 0:
        print("warning: no papers matched; check your --author/--orcid spelling")
    return 0


def _cmd_hqp(args: argparse.Namespace) -> int:
    from .hqp import update_hqp

    tree = xmlutil.load_ccv(args.base)
    info = update_hqp(
        tree,
        args.input,
        section_label=args.section,
        mode=args.mode,
        assign_record_ids=args.assign_record_ids,
    )
    xmlutil.write_ccv(tree, args.out)
    print(
        f"Wrote {args.out}: {info['written']} record(s) in section {info['section']!r}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ccv",
        description="Build Canadian Common CV (CCV) XML from a base CCV and BibTeX.",
    )
    parser.add_argument("--version", action="version", version=f"ccv {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser(
        "build",
        help="Replace Publications in a base CCV using a BibTeX file",
    )
    build.add_argument("--base", required=True, type=Path,
                       help="Existing CCV XML used as the structural base")
    build.add_argument("--bib", required=True, type=Path,
                       help="BibTeX file (article / inproceedings / inbook)")
    build.add_argument("--out", required=True, type=Path,
                       help="Output CCV XML path")
    build.add_argument("--since", default=None,
                       help="Only include entries on/after YYYY or YYYY-MM")
    build.add_argument("--last-years", type=int, default=None,
                       help="Include only the last N years (Discovery-style window)")
    build.add_argument("--author-surname", default="Fabbro",
                       help="Comma-separated surnames used to detect first/last "
                       "authorship (default: Fabbro)")
    build.add_argument("--overrides", type=Path, default=None,
                       help="YAML file with invited/refereed/status/percentage rules")
    build.add_argument("--preserve-extra", action="store_true",
                       help="Keep base publications that are absent from the BibTeX "
                       "instead of deleting them")
    build.add_argument("--assign-record-ids", action="store_true",
                       help="Assign new recordId attributes (default: omit them)")
    build.add_argument("-v", "--verbose", action="store_true")
    build.set_defaults(func=_cmd_build)

    summarize = sub.add_parser("summarize", help="Print section counts for a CCV XML")
    summarize.add_argument("--base", required=True, type=Path)
    summarize.add_argument("--json", action="store_true")
    summarize.set_defaults(func=_cmd_summarize)

    validate = sub.add_parser(
        "validate",
        help="Check publication records for fields the CCV import requires",
    )
    validate.add_argument("--base", required=True, type=Path)
    validate.add_argument("--strict", action="store_true",
                          help="Exit non-zero when issues are found")
    validate.set_defaults(func=_cmd_validate)

    fetch = sub.add_parser(
        "fetch",
        help="Pull BibTeX for your papers from the NASA ADS API",
    )
    fetch.add_argument("--out", required=True, type=Path,
                       help="Where to write the .bib file")
    fetch.add_argument("--token", default=None,
                       help="ADS API token (default: $ADS_API_TOKEN)")
    fetch.add_argument("--author", default=None,
                       help="ADS author phrase(s), e.g. 'Fabbro, S'. Multiple "
                       "surnames: 'Fabbro, Kavelaars' (initials stay glued to "
                       "their surname)")
    fetch.add_argument("--orcid", default=None, help="ORCID iD, e.g. 0000-0001-0000-0000")
    fetch.add_argument("--bibcodes", default=None,
                       help="Comma-separated list of ADS bibcodes")
    fetch.add_argument("--query", default=None,
                       help="Raw ADS search query (used only when --author/"
                       "--orcid/--bibcodes are not given)")
    fetch.add_argument("--max", type=int, default=1000,
                       help="Maximum number of papers to fetch (default 1000)")
    fetch.add_argument("--since-year", type=int, default=None,
                       help="Only keep papers from this year onward")
    fetch.set_defaults(func=_cmd_fetch)

    hqp = sub.add_parser(
        "hqp",
        help="Update the Students and Postdoctoral Fellows section from YAML",
    )
    hqp.add_argument("--base", required=True, type=Path)
    hqp.add_argument("--input", required=True, type=Path,
                     help="YAML file with a 'records' list of field-label dicts")
    hqp.add_argument("--out", required=True, type=Path)
    hqp.add_argument("--section", default=None,
                     help="Exact section label (default: auto-detect HQP section)")
    hqp.add_argument("--mode", choices=("replace", "append"), default="replace",
                     help="replace = rebuild from YAML; append = add without removing")
    hqp.add_argument("--assign-record-ids", action="store_true")
    hqp.set_defaults(func=_cmd_hqp)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
