import os
import requests


def run(ctx: dict):
    """
    Minimal Pipedrive connectivity test (read-only).
    Calls: GET https://api.pipedrive.com/v1/users/me?api_token=...
    """
    token = os.getenv("PIPEDRIVE_API_TOKEN")
    if not token:
        ctx["error"] = "Missing env var: PIPEDRIVE_API_TOKEN"
        return ctx

    base_url = os.getenv("PIPEDRIVE_BASE_URL", "https://api.pipedrive.com")
    url = f"{base_url}/v1/users/me"

    # Mask token in prints
    masked = f"...{token[-4:]}" if len(token) >= 4 else "***"

    print("\n=== STEP 05: Pipedrive PING ===")
    print(f"PIPEDRIVE_BASE_URL: {base_url}")
    print(f"PIPEDRIVE_API_TOKEN: {masked}")

    try:
        r = requests.get(url, params={"api_token": token}, timeout=30)
        print(f"HTTP: {r.status_code}")

        # Try JSON parse
        data = r.json()

        if r.status_code >= 400:
            ctx["error"] = f"Pipedrive error {r.status_code}: {data}"
            return ctx

        # Pipedrive typical shape: {"success": true, "data": {...}}
        success = data.get("success")
        me = data.get("data") or {}

        ctx["pipedrive_ping"] = {
            "success": bool(success),
            "user_id": me.get("id"),
            "name": me.get("name"),
            "email": me.get("email"),
            "company_id": me.get("company_id"),
        }

        print("PING OK:", ctx["pipedrive_ping"])
        return ctx

    except Exception as e:
        ctx["error"] = f"Pipedrive ping exception: {type(e).__name__}: {e}"
        return ctx
