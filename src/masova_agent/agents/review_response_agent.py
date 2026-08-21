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


async def draft_review_response(review_data: Dict[str, Any]) -> Dict[str, Any]:
    """Public entry — shared ops LLM tool loop + rule/template fallback."""
    from ..runtime.wrap import run_ops_agent
    from ..runtime.ops_llm import ops_prefer_llm

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
    rating = review_data.get("rating", 5)
    if rating > 3:
        return {"skipped": True, "reason": "Rating > 3, no response needed"}

    from ..utils.config import get_config

    config = get_config()
    backend_url = config.backend_url

    if not config.agent_token:
        logger.warning("AGENT_TOKEN not set — review response skipped")
        return {"error": "AGENT_TOKEN not configured"}

    headers = {"Authorization": f"Bearer {config.agent_token}", "Content-Type": "application/json"}

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
            order_res = await client.get(f"{backend_url}/api/orders/{order_id}", headers=headers)
            if order_res.status_code == 200:
                order = order_res.json()
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
            from google.genai import Client as GenAIClient

            genai_client = GenAIClient(api_key=config.google_api_key)
            response = genai_client.models.generate_content(
                model="gemini-2.5-flash-lite-preview-06-17",
                contents=prompt,
            )
            draft_response_text = response.text.strip()
        except Exception as e:
            logger.warning("Gemini call failed (%s), falling back to rule-based response", e)
            draft_response_text = _rule_based_response(review_text, rating, items_str, keywords)

        # Notify managers with the draft
        managers_res = await client.get(
            f"{backend_url}/api/users",
            params={"type": "MANAGER", "storeId": store_id},
            headers=headers,
        )

        if managers_res.status_code == 200:
            from . import _unwrap
            for manager in _unwrap(managers_res.json()):
                await client.post(
                    f"{backend_url}/api/notifications",
                    json={
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
                    headers=headers,
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
