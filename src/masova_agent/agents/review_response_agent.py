"""
Agent 5: Smart Review Response
Trigger: RabbitMQ event on new review with rating <= 3
Input: review text + order details + item names + complaint keywords
Output: draft personalised manager response pushed to notification feed
Uses LLM (Gemini 2.0 Flash Lite) — personalised, not a template
"""
import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

DRAFT_RESPONSE_PROMPT = """You are a professional restaurant manager writing a response to a customer review.

Review: {review_text}
Rating: {rating}/5
Items ordered: {items}
Complaint keywords: {keywords}

Write a personalised, empathetic response that:
1. Acknowledges the specific feedback (mention the items if relevant)
2. Apologises sincerely without being sycophantic
3. States what action will be taken (investigate, retrain staff, improve the dish)
4. Invites the customer back with goodwill

Maximum 100 words. No marketing language. No "We value your feedback" cliches.
"""




REVIEW_INSTRUCTION = """You are MaSoVa Review Response Agent (ops).
For low-rating reviews (<=3):
1. get_order_context if order_id is present (tool data for items).
2. Draft an empathetic reply using review text + order items only.
3. submit_review_draft_notification with draft_text and rationale.
Never post the review reply publicly — manager approval required.
Keep draft under 100 words. No marketing cliches.
"""


def _review_llm_runner(review_data: Dict[str, Any]):
    from ..runtime.ops_llm import make_ops_llm_runner
    from ..runtime.wrap import AGENT_ALLOWLISTS

    async def build_context(request):
        return {
            "review_id": review_data.get("reviewId"),
            "rating": review_data.get("rating"),
            "review_text": review_data.get("text", ""),
            "order_id": review_data.get("orderId"),
            "store_id": review_data.get("storeId"),
        }

    return make_ops_llm_runner(
        instruction=REVIEW_INSTRUCTION,
        tool_names=list(AGENT_ALLOWLISTS["review_response"]),
        build_context=build_context,
    )


async def latest_low_rating_review(store_id: str):
    """Newest rating≤3 review for the store (demo or platform)."""
    try:
        import httpx
        from ..tools.ops_http import agent_token, get_json, unwrap_list

        if not agent_token() or not store_id:
            return None
        async with httpx.AsyncClient(timeout=15.0) as client:
            status, body = await get_json(client, "/api/reviews", params={"storeId": store_id})
            if status != 200:
                return None
            for row in unwrap_list(body):
                rating = int(row.get("rating") or 5)
                if rating <= 3:
                    return {
                        "reviewId": row.get("id") or row.get("reviewId"),
                        "rating": rating,
                        "text": row.get("text") or row.get("comment") or "",
                        "storeId": row.get("storeId") or store_id,
                        "orderId": row.get("orderId"),
                    }
    except Exception as e:
        logger.warning("low-rating review lookup failed: %s", e)
    return None


async def draft_review_response(review_data: Dict[str, Any]) -> Dict[str, Any]:
    """Public entry — shared ops LLM tool loop + rule/template fallback."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm

    store_id = review_data.get("storeId") or review_data.get("store_id")
    if store_id and not review_data.get("reviewId"):
        found = await latest_low_rating_review(str(store_id))
        if not found:
            return {
                "skipped": True,
                "reason": "no_low_rating_review",
                "store_id": store_id,
                "status": "ok",
                "summary": "no low-rating review for store",
            }
        merged = dict(found)
        merged.update({k: v for k, v in review_data.items() if v not in (None, "")})
        review_data = merged

    async def _fb():
        return await _rule_draft_review_response(review_data)

    prefer = ops_prefer_llm()
    return await run_ops_agent(
        "review_response",
        "event",
        _fb,
        store_id=review_data.get("storeId"),
        goal="Draft manager reply for low-rating review",
        context={
            "review_id": review_data.get("reviewId"),
            "rating": review_data.get("rating"),
            "review_text": (review_data.get("text") or "")[:500],
            "order_id": review_data.get("orderId"),
        },
        llm_runner=_review_llm_runner(review_data) if prefer else None,
        prefer_llm=prefer,
    )

async def _rule_draft_review_response(review_data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a draft response for a low-rating review."""
    from ..tools.ops_http import agent_token, get_json, post_json, unwrap_list

    rating = review_data.get("rating", 5)
    if rating > 3:
        return {"skipped": True, "reason": "Rating > 3, no response needed"}

    if not agent_token():
        logger.warning("AGENT_TOKEN not set — review response skipped")
        return {"error": "AGENT_TOKEN not configured"}

    review_id = review_data.get("reviewId")
    rating = review_data.get("rating", 0)
    review_text = review_data.get("text", "")
    store_id = review_data.get("storeId")
    order_id = review_data.get("orderId")

    if rating > 3:
        return {"skipped": True, "reason": "Rating > 3, no response needed"}

    # Fetch order details for context
    items_str = ""
    async with httpx.AsyncClient(timeout=15.0) as client:
        if order_id:
            order_status, order = await get_json(client, f"/api/orders/{order_id}")
            if order_status == 200:
                items_str = ", ".join(i.get("name", "?") for i in order.get("items", []))

        # Generate response using Gemini
        keywords = _extract_keywords(review_text)
        prompt = DRAFT_RESPONSE_PROMPT.format(
            review_text=review_text,
            rating=rating,
            items=items_str or "unspecified items",
            keywords=", ".join(keywords) or "general dissatisfaction",
        )

        try:
            from ..utils.config import get_config
            from ..runtime.ops_llm import make_genai_client

            config = get_config()
            genai_client = make_genai_client(config.google_api_key or None)
            response = genai_client.models.generate_content(
                model=config.llm_model or "gemini-3.5-flash",
                contents=prompt,
            )
            draft_response_text = response.text.strip()
        except Exception as e:
            logger.warning("Gemini call failed (%s), falling back to rule-based response", e)
            draft_response_text = _rule_based_response(review_text, rating, items_str, keywords)

        # Notify managers with the draft
        managers_status, managers = await get_json(
            client,
            "/api/users",
            params={"type": "MANAGER", "storeId": store_id},
        )

        if managers_status == 200:
            for manager in unwrap_list(managers):
                await post_json(
                    client,
                    "/api/notifications",
                    {
                        "userId": manager["id"],
                        "type": "REVIEW_DRAFT_RESPONSE",
                        "title": f"New {rating}\u2605 Review — Draft Response Ready",
                        "message": (
                            f"Review: \"{review_text[:80]}...\"\n\n"
                            f"Draft response: {draft_response_text}"
                        ),
                        "data": {
                            "reviewId": review_id,
                            "draftResponse": draft_response_text,
                        },
                        "priority": "HIGH" if rating == 1 else "MEDIUM",
                    },
                )

    logger.info("Draft response generated for review %s (rating: %d)", review_id, rating)
    return {"reviewId": review_id, "draftGenerated": True, "responseLength": len(draft_response_text)}


def _extract_keywords(text: str) -> list:
    """Extract complaint keywords from review text."""
    complaint_terms = [
        "cold", "slow", "late", "wrong", "missing", "rude", "dirty",
        "overpriced", "raw", "burnt", "stale", "hair", "wait", "cancelled",
        "never arrived", "incorrect",
    ]
    text_lower = text.lower()
    return [term for term in complaint_terms if term in text_lower]


def _rule_based_response(review_text: str, rating: int, items: str, keywords: list) -> str:
    """Fallback response when Gemini is unavailable."""
    issue = keywords[0] if keywords else "your experience"
    item_mention = f" with {items}" if items else ""
    return (
        f"Thank you for your honest feedback. We're sorry to hear about {issue}{item_mention}. "
        f"Our team is looking into this and we'll take steps to improve. "
        f"We'd love the chance to make it right — please visit us again soon."
    )
