"""
Test Google GenAI API connection
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from masova_agent import get_config, get_logger
from google import genai

logger = get_logger(__name__)


def main():
    """Test API connection"""
    print("🔌 Testing Google GenAI API Connection...")
    print("=" * 60)

    try:
        # Get config
        config = get_config()
        print(f"✅ Configuration loaded")
        print(f"   Model: {config.agent.model}")
        print(f"   Use Vertex AI: {config.api.use_vertex_ai}")

        # Test API call
        print("\n📡 Making test API call...")
        client = genai.Client(api_key=config.api.google_api_key)
        response = client.models.generate_content(
            model=config.agent.model,
            contents="Say 'Connection successful' in exactly two words."
        )

        print(f"\n✅ API Response:")
        print(f"   {response.text}")

        print("\n" + "=" * 60)
        print("✅ Connection test PASSED!")
        print("=" * 60)
        return 0

    except Exception as e:
        logger.error(f"Connection test failed: {e}", exc_info=True)
        print(f"\n❌ Connection test FAILED:")
        print(f"   {e}")
        print("\n" + "=" * 60)
        print("❌ Please check your GOOGLE_API_KEY in .env")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    exit(main())
