"""
Signal Account Setup Helper for signal-cli-rest-api.
Links your phone as a secondary device.
"""

import os
import sys
import time
import urllib.parse

import httpx
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("SIGNAL_API_URL", "http://localhost:18080")
PHONE_NUMBER = os.getenv("SIGNAL_PHONE_NUMBER")


def wait_for_api():
    """Wait for the API to be ready."""
    print(f"Connecting to Signal API at {API_URL}...")
    for i in range(30):
        try:
            r = httpx.get(f"{API_URL}/v1/about", timeout=5)
            if r.status_code == 200:
                print(f"✓ Connected! {r.json()}")
                return
        except Exception:
            pass
        print(f"  Waiting... ({i + 1}/30)")
        time.sleep(2)
    print("ERROR: Signal API not reachable.")
    sys.exit(1)


def list_accounts():
    """List registered accounts."""
    r = httpx.get(f"{API_URL}/v1/accounts", timeout=10)
    accounts = r.json() if r.status_code == 200 else []
    if accounts:
        print("\n=== Registered Accounts ===")
        for acc in accounts:
            print(f"  • {acc}")
        print()
    else:
        print("\nNo accounts registered yet.\n")
    return accounts


def link_device():
    """Link as a secondary device (like Signal Desktop)."""
    print()
    print("=" * 50)
    print("  Link as Secondary Device")
    print("=" * 50)
    print()
    print("This links signal-cli to your existing Signal account,")
    print("just like linking Signal Desktop.")
    print()

    # Get the QR code link URI
    device_name = input("Device name (default: 'Ollama Signal Bot'): ").strip()
    if not device_name:
        device_name = "Ollama Signal Bot"

    print()
    print("Requesting linking QR code...")
    print()

    # The /v1/qrcodelink endpoint returns a QR code image
    qr_url = f"{API_URL}/v1/qrcodelink?device_name={urllib.parse.quote(device_name)}"

    print("Open this URL in your browser to see the QR code:")
    print(f"  {qr_url}")
    print()
    print("Then on your phone:")
    print("  1. Open Signal → Settings → Linked Devices")
    print("  2. Tap '+' or 'Link New Device'")
    print("  3. Scan the QR code from the browser page")
    print()

    input("Press Enter after scanning and approving on your phone...")

    # Check if linking succeeded
    accounts = list_accounts()
    if accounts:
        print("✓ Device linked successfully!")
        return True
    else:
        print("Linking may still be in progress. Check accounts in a moment.")
        return False


def main():
    print()
    print("=" * 50)
    print("  Signal Account Setup Helper")
    print("  (using signal-cli-rest-api)")
    print("=" * 50)
    print()

    wait_for_api()
    accounts = list_accounts()

    if PHONE_NUMBER and PHONE_NUMBER in accounts:
        print(f"✓ Account {PHONE_NUMBER} is already registered!")
        print("Start the bot with: docker-compose up -d")
        return

    while True:
        print("What would you like to do?")
        print()
        print("  1. Link as secondary device (scan QR from phone)")
        print("  2. List accounts")
        print("  3. Exit")
        print()

        choice = input("Enter choice (1-3): ").strip()

        if choice == "1":
            if link_device():
                print("\n🎉 Setup complete! Start the bot with:")
                print("   docker-compose up -d")
                return

        elif choice == "2":
            list_accounts()

        elif choice == "3":
            print("Goodbye!")
            return

        else:
            print("Invalid choice.\n")


if __name__ == "__main__":
    main()