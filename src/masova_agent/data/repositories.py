"""
Data repositories for MaSoVa Agent
"""
from typing import Optional, List
from .models import Customer, Order, CustomerTier, OrderStatus


class CustomerRepository:
    """Repository for customer data operations"""

    def __init__(self):
        """Initialize with mock data (replace with MongoDB later)"""
        self._customers = {
            "c1": {
                "customerId": "CUST-001",
                "name": "Soura Vamseekar",
                "tier": "GOLD",
                "loyaltyPoints": 1250,
                "email": "soura@masova.com",
                "phone": "+91-9876543210"
            }
        }

    def find_by_name(self, name: str) -> Optional[Customer]:
        """
        Find customer by name (fuzzy matching)

        Args:
            name: Customer name to search for

        Returns:
            Customer object if found, None otherwise
        """
        name_lower = name.lower()
        for customer_data in self._customers.values():
            if name_lower in customer_data["name"].lower():
                return Customer.from_dict(customer_data)
        return None

    def find_by_id(self, customer_id: str) -> Optional[Customer]:
        """
        Find customer by ID

        Args:
            customer_id: Customer ID to search for

        Returns:
            Customer object if found, None otherwise
        """
        for customer_data in self._customers.values():
            if customer_data["customerId"] == customer_id:
                return Customer.from_dict(customer_data)
        return None

    def get_all(self) -> List[Customer]:
        """Get all customers"""
        return [Customer.from_dict(data) for data in self._customers.values()]

    def save(self, customer: Customer) -> None:
        """Save or update customer"""
        existing = next(
            (k for k, v in self._customers.items() if v["customerId"] == customer.customer_id),
            None,
        )
        key = existing or f"c{max((int(k[1:]) for k in self._customers if k[1:].isdigit()), default=0) + 1}"
        self._customers[key] = customer.to_dict()


class OrderRepository:
    """Repository for order data operations"""

    def __init__(self):
        """Initialize with mock data (replace with MongoDB later)"""
        self._orders = {
            "ord1": {
                "orderId": "ORD-20260216-102",
                "customerId": "CUST-001",
                "item": "Chicken Biryani",
                "status": "OUT_FOR_DELIVERY",
                "quantity": 1,
                "totalAmount": 299.00
            }
        }

    def find_by_customer_id(self, customer_id: str) -> List[Order]:
        """
        Find all orders for a customer

        Args:
            customer_id: Customer ID to search for

        Returns:
            List of Order objects
        """
        orders = []
        for order_data in self._orders.values():
            if order_data["customerId"] == customer_id:
                orders.append(Order.from_dict(order_data))
        return orders

    def find_active_orders(self, customer_id: str) -> List[Order]:
        """
        Find active orders (not delivered/cancelled) for a customer

        Args:
            customer_id: Customer ID to search for

        Returns:
            List of active Order objects
        """
        active_statuses = {
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.OUT_FOR_DELIVERY,
        }

        orders = []
        for order_data in self._orders.values():
            if order_data["customerId"] == customer_id:
                order = Order.from_dict(order_data)
                if order.status in active_statuses:
                    orders.append(order)
        return orders

    def find_by_id(self, order_id: str) -> Optional[Order]:
        """Find order by ID"""
        for order_data in self._orders.values():
            if order_data["orderId"] == order_id:
                return Order.from_dict(order_data)
        return None

    def save(self, order: Order) -> None:
        """Save or update order"""
        existing = next(
            (k for k, v in self._orders.items() if v["orderId"] == order.order_id),
            None,
        )
        key = existing or f"ord{max((int(k[3:]) for k in self._orders if k[3:].isdigit()), default=0) + 1}"
        self._orders[key] = order.to_dict()
