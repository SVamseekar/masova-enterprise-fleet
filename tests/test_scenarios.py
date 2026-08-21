"""
Test scenarios for MaSoVa Agent
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from masova_agent.agent import send_message
from masova_agent.utils import get_logger

logger = get_logger(__name__)


def test_scenario(description: str, message: str, user_id: str = "test_user") -> bool:
    """
    Test a specific scenario with the MaSoVa agent.

    Args:
        description: Description of the test scenario
        message: The user message to send
        user_id: User identifier for the test session

    Returns:
        True if test passed, False otherwise
    """
    print("\n" + "=" * 60)
    print(f"📋 Scenario: {description}")
    print("=" * 60)
    print(f"💬 User: {message}")

    try:
        # Each test gets its own session to avoid context pollution
        session_id = f"test_{description.replace(' ', '_').lower()}"
        response = send_message(message, user_id=user_id, session_id=session_id)

        print(f"\n🤖 Agent Response:\n{response}")
        print("\n✅ Test completed successfully")
        return True

    except Exception as e:
        logger.error(f"Test failed for scenario '{description}': {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        return False


def main():
    """Run all test scenarios"""
    print("\n🧪 Running MaSoVa Agent Test Scenarios")
    print("=" * 60)

    results = []

    # Test 1: User identification and system briefing
    results.append(test_scenario(
        "User Identification",
        "Hi, I'm Soura"
    ))

    # Test 2: General menu inquiry
    results.append(test_scenario(
        "Menu Inquiry",
        "Hi, what do you have to eat today?"
    ))

    # Test 3: Specific item check
    results.append(test_scenario(
        "Item Availability",
        "Is the Pepperoni pizza available?"
    ))

    # Test 4: Order placement
    results.append(test_scenario(
        "Order Placement",
        "I'd like to order a Margherita pizza and Garlic Bread. "
        "My name is Sourav and I'm at 123 Pizza Lane."
    ))

    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    print(f"Failed: {total - passed}/{total}")

    if passed == total:
        print("\n✅ All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit(main())
