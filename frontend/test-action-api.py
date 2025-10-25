#!/usr/bin/env python3
"""
Test script to send current action updates to the Cluely widget
Run this with: python3 test-action-api.py

This demonstrates how your Flask server can send updates to the widget
"""

import requests
import time

def send_current_action(action):
    """Send current action to Cluely widget"""
    try:
        response = requests.post(
            'http://localhost:3456/api/currentaction',
            data=action,
            headers={'Content-Type': 'text/plain'}
        )
        print(f"Sent: {action}")
        print(f"Response: {response.status_code} - {response.json()}\n")
        return response.json()
    except Exception as e:
        print(f"Error sending action: {e}\n")
        return None

if __name__ == "__main__":
    print("Sending test actions to Cluely widget...\n")

    # Simulate agent actions
    send_current_action("Agent is thinking...")
    time.sleep(2)

    send_current_action("Opening calendar app...")
    time.sleep(2)

    send_current_action("Creating new event...")
    time.sleep(2)

    send_current_action("Setting event time for tomorrow at 12pm...")
    time.sleep(2)

    send_current_action("Event created successfully!")

    print("\nAll actions sent!")
