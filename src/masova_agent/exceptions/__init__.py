"""
Custom exceptions for MaSoVa Agent
"""


class MaSoVaException(Exception):
    """Base exception for all MaSoVa errors"""
    pass


class CustomerNotFoundError(MaSoVaException):
    """Raised when customer is not found in database"""
    def __init__(self, identifier: str):
        self.identifier = identifier
        super().__init__(f"Customer not found: {identifier}")


class OrderNotFoundError(MaSoVaException):
    """Raised when order is not found"""
    def __init__(self, order_id: str):
        self.order_id = order_id
        super().__init__(f"Order not found: {order_id}")


class LocationServiceError(MaSoVaException):
    """Raised when location service fails"""
    def __init__(self, message: str = "Location service unavailable"):
        super().__init__(message)


class ConfigurationError(MaSoVaException):
    """Raised when configuration is invalid"""
    pass


class AgentError(MaSoVaException):
    """Raised when agent encounters an error"""
    pass


__all__ = [
    "MaSoVaException",
    "CustomerNotFoundError",
    "OrderNotFoundError",
    "LocationServiceError",
    "ConfigurationError",
    "AgentError",
]
