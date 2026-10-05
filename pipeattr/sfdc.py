"""Minimal read-only Salesforce REST client (stdlib only)."""
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request


def get_credentials(org_alias=None):
    """Return (instance_url, access_token).

    Uses SF_INSTANCE_URL + SF_ACCESS_TOKEN if both are set; otherwise asks the
    Salesforce CLI: `sf org display --json [--target-org <alias>]`.
    """
    url, token = os.environ.get("SF_INSTANCE_URL"), os.environ.get("SF_ACCESS_TOKEN")
    if url and token:
        return url.rstrip("/"), token
    cmd = ["sf", "org", "display", "--json"]
    if org_alias:
        cmd += ["--target-org", org_alias]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("Set SF_INSTANCE_URL and SF_ACCESS_TOKEN, or install the Salesforce CLI (`sf`).")
    if res.returncode != 0:
        raise RuntimeError(f"`sf org display` failed. Log in with `sf org login web`.\n{res.stderr.strip()}")
    data = json.loads(res.stdout)["result"]
    return data["instanceUrl"].rstrip("/"), data["accessToken"]


class Client:
    def __init__(self, instance_url, access_token, api_version="v60.0"):
        self.instance_url = instance_url
        self.token = access_token
        self.api_version = api_version

    def _get(self, path):
        req = urllib.request.Request(
            self.instance_url + path, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Salesforce API error {e.code}: {e.read().decode(errors='replace')[:500]}")

    def query(self, soql):
        """Run a SOQL query and follow pagination. Returns a list of record dicts."""
        path = f"/services/data/{self.api_version}/query/?q={urllib.parse.quote(soql)}"
        records = []
        while path:
            page = self._get(path)
            records.extend(page.get("records", []))
            path = page.get("nextRecordsUrl")
        return records

    def field_type(self, sobject, field):
        """Return the Salesforce type of a field ('date', 'datetime', ...), or None."""
        desc = self._get(f"/services/data/{self.api_version}/sobjects/{sobject}/describe/")
        for f in desc["fields"]:
            if f["name"].lower() == field.lower():
                return f["type"]
        return None
