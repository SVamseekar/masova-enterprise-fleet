"""
Order service for business logic
"""
from typing import List, Optional

from ..data import Order, OrderRepository, Customer
from ..exceptions import OrderNotFoundError
from ..utils import get_logger

logger = get_logger(__name__)


class OrderService:
    """Service for order-related operations"""

    def __init__(self, repository: Optional[OrderRepository] = None):
        """
        Initialize order service

        Args:
            repository: Order repository (default: creates new instance)
        """
        self.repository = repository or OrderRepository()

    def get_customer_orders(self, customer: Customer) -> List[Order]:
        """
        Get all orders for a customer

        Args:
            customer: Customer object

        Returns:
            List of orders
        """
        logger.debug(f"Fetching orders for customer: {customer.customer_id}")
        orders = self.repository.find_by_customer_id(customer.customer_id)
        logger.info(f"Found {len(orders)} orders for {customer.name}")
        return orders

    def get_active_orders(self, customer: Customer) -> List[Order]:
        """
        Get active orders for a customer

        Args:
            customer: Customer object

        Returns:
            List of active orders
        """
        logger.debug(f"Fetching active orders for: {customer.customer_id}")
        orders = self.repository.find_active_orders(customer.customer_id)
        logger.info(f"Found {len(orders)} active orders for {customer.name}")
        return orders

    def get_order(self, order_id: str) -> Order:
        """
        Get specific order by ID

        Args:
            order_id: Order ID

        Returns:
            Order object

        Raises:
            OrderNotFoundError: If order not found
        """
        logger.debug(f"Fetching order: {order_id}")
        order = self.repository.find_by_id(order_id)

        if not order:
            logger.warning(f"Order not found: {order_id}")
            raise OrderNotFoundError(order_id)

        logger.info(f"Found order: {order_id}")
        return order

    def format_order_status(self, orders: List[Order]) -> str:
        """
        Format order list for display

        Args:
            orders: List of orders

        Returns:
            Formatted string
        """
        if not orders:
            return "No active orders."

        if len(orders) == 1:
            order = orders[0]
            return f"**{order.item}** ({order.order_id}) is **{order.status.value}**."

        # Multiple orders
        lines = []
        for order in orders:
            lines.append(f"- **{order.item}** ({order.order_id}): **{order.status.value}**")
        return "\n".join(lines)
