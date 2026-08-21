"""
Interactive chat interface for MaSoVa Agent
"""
from masova_agent import send_message, get_logger, AgentError

logger = get_logger(__name__)


def main():
    """Main chat loop"""
    print("=" * 60)
    print("   MaSoVa Agent - Interactive Chat")
    print("=" * 60)
    print("Type 'exit' or 'quit' to end the session.\n")

    session_id = "interactive_chat_session"
    user_id = "chat_user"
    message_count = 0

    while True:
        try:
            user_input = input("\n💬 You: ")

            if user_input.lower() in ["exit", "quit"]:
                print("\n👋 Thank you for using MaSoVa! Goodbye!")
                logger.info(f"Chat session ended. Messages: {message_count}")
                break

            if not user_input.strip():
                continue

            message_count += 1

            # Send message to agent
            response = send_message(user_input, user_id=user_id, session_id=session_id)
            print(f"\n🤖 MaSoVa:\n{response}")

        except KeyboardInterrupt:
            print("\n\n👋 Session interrupted. Goodbye!")
            logger.info(f"Chat interrupted. Messages: {message_count}")
            break

        except AgentError as e:
            logger.error(f"Agent error: {e}")
            print(f"\n❌ Agent Error: {e}")
            print("Please try again or type 'exit' to quit.")

        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            print(f"\n❌ Unexpected Error: {e}")
            print("Please try again or type 'exit' to quit.")


if __name__ == "__main__":
    main()
