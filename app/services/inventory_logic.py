from typing import Any, Dict, List, Optional


def select_best_listing(listings: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not listings:
        return None

    def _active_rank(item: Dict[str, Any]) -> int:
        status = str(item.get("status") or "").lower()
        if status == "active":
            return 1
        if item.get("is_active") is True:
            return 1
        return 0

    def _last_seen(item: Dict[str, Any]):
        return item.get("last_seen_at") or ""

    return sorted(listings, key=lambda x: (_active_rank(x), _last_seen(x)), reverse=True)[0]
