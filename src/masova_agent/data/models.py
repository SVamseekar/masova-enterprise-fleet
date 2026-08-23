"""
Data models for MaSoVa Agent
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime


class CustomerTier(Enum):
    """Customer tier levels"""
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class OrderStatus(Enum):
    """Order status states"""
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PREPARING = "PREPARING"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


@dataclass
class Customer:
    """Customer data model"""
    customer_id: str
    name: str
    tier: CustomerTier
    loyalty_points: int
    email: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Customer":
        """Create Customer from dictionary"""
        return cls(
            customer_id=data["customerId"],
            name=data["name"],
            tier=CustomerTier(data["tier"]),
            loyalty_points=data["loyaltyPoints"],
            email=data.get("email"),
            phone=data.get("phone"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "customerId": self.customer_id,
            "name": self.name,
            "tier": self.tier.value,
            "loyaltyPoints": self.loyalty_points,
            "email": self.email,
            "phone": self.phone,
        }


@dataclass
class Order:
    """Order data model"""
    order_id: str
    customer_id: str
    item: str
    status: OrderStatus
    quantity: int = 1
    total_amount: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Order":
        """Create Order from dictionary"""
        return cls(
            order_id=data["orderId"],
            customer_id=data["customerId"],
            item=data["item"],
            status=OrderStatus(data["status"]),
            quantity=data.get("quantity", 1),
            total_amount=data.get("totalAmount"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "orderId": self.order_id,
            "customerId": self.customer_id,
            "item": self.item,
            "status": self.status.value,
            "quantity": self.quantity,
            "totalAmount": self.total_amount,
        }


@dataclass
class Location:
    """Geographic location data"""
    city: str
    country: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    region: Optional[str] = None

    def __str__(self) -> str:
        """String representation"""
        return f"{self.city}, {self.country}"
