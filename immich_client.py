"""
immich_client.py
Thin client around the Immich API for listing assets.

Immich's API has changed across versions. This client tries the modern
paginated search endpoint first and falls back to the older /api/asset
endpoint if needed. Adjust as needed for your specific Immich version.
"""
import requests


class ImmichClient:
    def __init__(self, base_url, api_key, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "Accept": "application/json",
        })

    def test_connection(self):
        """Returns (ok, message)"""
        try:
            r = self.session.get(f"{self.base_url}/api/server/ping", timeout=self.timeout)
            if r.status_code == 200:
                return True, "Connected"
            # older versions: try /api/server-info/ping
            r2 = self.session.get(f"{self.base_url}/api/server-info/ping", timeout=self.timeout)
            if r2.status_code == 200:
                return True, "Connected"
            return False, f"Unexpected status {r.status_code}"
        except requests.RequestException as e:
            return False, str(e)

    def iter_all_assets(self, page_size=500):
        """
        Yields asset dicts with at least: id, originalPath, checksum, originalFileName, fileCreatedAt
        Tries the metadata search endpoint (POST /api/search/metadata) which supports pagination,
        falling back to GET /api/asset for older Immich versions.
        """
        page = 1
        try:
            while True:
                resp = self.session.post(
                    f"{self.base_url}/api/search/metadata",
                    json={"page": page, "size": page_size, "withDeleted": False},
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                items = data.get("assets", {}).get("items", [])
                if not items:
                    break
                for item in items:
                    yield item
                if not data.get("assets", {}).get("nextPage"):
                    break
                page = data["assets"]["nextPage"]
            return
        except requests.RequestException:
            pass

        # Fallback: older flat endpoint
        try:
            resp = self.session.get(f"{self.base_url}/api/asset", timeout=self.timeout)
            resp.raise_for_status()
            for item in resp.json():
                yield item
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch assets from Immich: {e}")
