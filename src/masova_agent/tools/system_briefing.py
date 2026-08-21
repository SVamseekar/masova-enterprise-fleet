"""
System briefing tool for agent
"""
from typing import Optional

from ..services import CustomerService, OrderService, LocationService
from ..exceptions import CustomerNotFoundError, LocationServiceError
from ..utils import get_logger

logger = get_logger(__name__)


class SystemBriefingTool:
    """Tool for generating system briefings"""

    def __init__(
        self,
        customer_service: Optional[CustomerService] = None,
        order_service: Optional[OrderService] = None,
        location_service: Optional[LocationService] = None
    ):
        """
        Initialize briefing tool

        Args:
            customer_service: Customer service instance
            order_service: Order service instance
            location_service: Location service instance
        """
        self.customer_service = customer_service or CustomerService()
        self.order_service = order_service or OrderService()
        self.location_service = location_service or LocationService()

    def get_briefing(self, user_name: str) -> str:
        """
        Generate system briefing for a user

        Args:
            user_name: User's name

        Returns:
            Formatted briefing string
        """
        logger.info(f"Generating briefing for: {user_name}")

        try:
            # Find customer
            customer = self.customer_service.find_customer(user_name)

            # Get location (with caching)
            try:
                location = self.location_service.get_location(customer.customer_id)
                location_str = f"📍 {location}"
            except LocationServiceError as e:
                logger.warning(f"Location service error: {e}")
                location_str = "📍 Encrypted"

            # Get active orders
            orders = self.order_service.get_active_orders(customer)
            order_info = self.order_service.format_order_status(orders)

            # Format briefing
            briefing = f"""
### 🛡️ MaSoVa System Briefing

**Identity:** {customer.name}
**Role:** {customer.tier.value} Member ({customer.loyalty_points} pts)
**Location:** {location_str}

---
**📦 Order Status:**
{order_info}
            """.strip()

            logger.info(f"Briefing generated successfully for {customer.name}")
            return briefing

        except CustomerNotFoundError:
            error_msg = f"ERROR: Access Denied. User not found in MaSoVa Database."
            logger.warning(f"Briefing failed: {error_msg}")
            return error_msg
        except Exception as e:
            logger.error(f"Unexpected error generating briefing: {e}", exc_info=True)
            return f"ERROR: System error occurred. Please try again later."


# Global instance for ADK tool registration
_briefing_tool = None


def get_system_briefing(user_name: str) -> str:
    """
    Get system briefing (ADK tool function)

    Args:
        user_name: User's name

    Returns:
        System briefing string
    """
    global _briefing_tool
    if _briefing_tool is None:
        _briefing_tool = SystemBriefingTool()

    return _briefing_tool.get_briefing(user_name)
