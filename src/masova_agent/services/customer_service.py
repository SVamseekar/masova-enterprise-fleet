"""
Customer service for business logic
"""
from typing import Optional, List

from ..data import Customer, CustomerRepository
from ..exceptions import CustomerNotFoundError
from ..utils import get_logger

logger = get_logger(__name__)


class CustomerService:
    """Service for customer-related operations"""

    def __init__(self, repository: Optional[CustomerRepository] = None):
        """
        Initialize customer service

        Args:
            repository: Customer repository (default: creates new instance)
        """
        self.repository = repository or CustomerRepository()

    def find_customer(self, identifier: str) -> Customer:
        """
        Find customer by name or ID

        Args:
            identifier: Customer name or ID

        Returns:
            Customer object

        Raises:
            CustomerNotFoundError: If customer not found
        """
        logger.debug(f"Searching for customer: {identifier}")

        # Try by name first (more common in chat)
        customer = self.repository.find_by_name(identifier)

        # Try by ID if name search failed
        if not customer:
            customer = self.repository.find_by_id(identifier)

        if not customer:
            logger.warning(f"Customer not found: {identifier}")
            raise CustomerNotFoundError(identifier)

        logger.info(f"Found customer: {customer.name} ({customer.customer_id})")
        return customer

    def get_all_customers(self) -> List[Customer]:
        """Get all customers"""
        return self.repository.get_all()

    def verify_customer(self, name: str) -> bool:
        """
        Verify if customer exists

        Args:
            name: Customer name

        Returns:
            True if customer exists, False otherwise
        """
        try:
            self.find_customer(name)
            return True
        except CustomerNotFoundError:
            return False
