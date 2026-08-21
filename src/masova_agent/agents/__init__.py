"""MaSoVa background agents (Agents 2–8)."""


def _unwrap(data) -> list:
    """Extract a list from either a plain list or a paginated dict with 'content'."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("content") or []
    return []
