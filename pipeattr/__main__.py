"""Command line: python3 -m pipeattr [--offline DIR] [--config FILE] [--out DIR]"""
import argparse
import os
import sys

from .analyze import analyze
from .config import load_config
from .data import load_offline, load_salesforce
from .report import render_html, write_csvs
from .sfdc import Client, get_credentials


def main(argv=None):
    p = argparse.ArgumentParser(prog="pipeattr", description=__doc__)
    p.add_argument("--offline", metavar="DIR", help="read fixtures from DIR instead of Salesforce")
    p.add_argument("--config", metavar="FILE", help="config JSON (default: ./config.json if present)")
    p.add_argument("--org", metavar="ALIAS", help="Salesforce CLI org alias (overrides sf_org_alias)")
    p.add_argument("--since", metavar="YYYY-MM-DD", help="only opportunities that entered pipeline on/after this date")
    p.add_argument("--out", default="output", metavar="DIR")
    a = p.parse_args(argv)

    cfg_path = a.config
    if cfg_path is None and a.offline:
        cand = os.path.join(a.offline, "sample_config.json")
        cfg_path = cand if os.path.exists(cand) else None
    if cfg_path is None and os.path.exists("config.json") and not a.offline:
        cfg_path = "config.json"
    cfg = load_config(cfg_path)
    if a.since:
        cfg["since"] = a.since

    if a.offline:
        raw = load_offline(a.offline)
    else:
        url, token = get_credentials(a.org or cfg["sf_org_alias"])
        raw = load_salesforce(Client(url, token, cfg["api_version"]), cfg)

    res = analyze(raw, cfg)
    os.makedirs(a.out, exist_ok=True)
    html_path = os.path.join(a.out, "report.html")
    with open(html_path, "w") as f:
        f.write(render_html(res, cfg))
    csvs = write_csvs(res, cfg, a.out)
    d, cov = res["dashboard"], res["coverage"]
    print(f"{d['total']} opportunities, {cov['with_touches']} with touches ({cov['pct']:.0%})")
    print("wrote", html_path, *csvs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
