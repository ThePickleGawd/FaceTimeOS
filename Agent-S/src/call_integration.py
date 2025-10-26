"""Integration module for Agent-S to interact with the backend call system."""
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Any

import requests
from dotenv import load_dotenv

# Load environment variables
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Backend server configuration
BACKEND_HOST = os.getenv("SERVER_HOST")
BACKEND_PORT = os.getenv("SERVER_PORT")
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"


class CallIntegration:
    """Handles integration between Agent-S and the backend call system."""
    
    def __init__(self):
        self.backend_url = BACKEND_URL
        self.call_active = False
        self.current_call_id = None
        logger.info(f"Call integration initialized with backend at {self.backend_url}")
    
    def notify_call_started(self, caller: Optional[str] = None, 
                           call_id: Optional[str] = None,
                           metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Notify the backend that a FaceTime call has been initiated.
        
        Args:
            caller: The caller's identifier (phone number, email, etc.)
            call_id: Unique identifier for this call session
            metadata: Additional metadata about the call
            
        Returns:
            True if notification was successful, False otherwise
        """
        endpoint = f"{self.backend_url}/api/call_started"
        
        payload = {
            "caller": caller,
            "call_id": call_id or f"call_{os.getpid()}_{int(time.time())}",
            "metadata": metadata or {}
        }
        
        try:
            logger.info(f"Notifying backend of call start: {payload}")
            response = requests.post(endpoint, json=payload, timeout=5)
            
            if response.status_code == 200:
                result = response.json()
                self.call_active = result.get("call_active", False)
                self.current_call_id = payload["call_id"]
                logger.info(f"Call started successfully: {result}")
                return True
            else:
                logger.error(f"Failed to start call: {response.status_code} - {response.text}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"Error notifying backend of call start: {e}")
            return False
    
    def notify_call_ended(self, call_id: Optional[str] = None) -> bool:
        """
        Notify the backend that the FaceTime call has ended.
        
        Args:
            call_id: The call ID to end (uses current if not provided)
            
        Returns:
            True if notification was successful, False otherwise
        """
        endpoint = f"{self.backend_url}/api/call_ended"
        
        payload = {
            "call_id": call_id or self.current_call_id
        }
        
        try:
            logger.info(f"Notifying backend of call end: {payload}")
            response = requests.post(endpoint, json=payload, timeout=5)
            
            if response.status_code == 200:
                result = response.json()
                self.call_active = False
                self.current_call_id = None
                logger.info(f"Call ended successfully: {result}")
                return True
            else:
                logger.error(f"Failed to end call: {response.status_code} - {response.text}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"Error notifying backend of call end: {e}")
            return False
    
    def get_call_status(self) -> Optional[Dict[str, Any]]:
        """
        Get the current status of the call system.
        
        Returns:
            Dictionary with call status or None if request failed
        """
        endpoint = f"{self.backend_url}/api/call_status"
        
        try:
            response = requests.get(endpoint, timeout=5)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get call status: {response.status_code}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"Error getting call status: {e}")
            return None
    
    def send_text_to_backend(self, text: str) -> bool:
        """
        Send text message to the backend for processing during a call.
        
        Args:
            text: Text message to send
            
        Returns:
            True if successful, False otherwise
        """
        if not self.call_active:
            logger.warning("No active call, cannot send text")
            return False
        
        endpoint = f"{self.backend_url}/api/chat"
        
        payload = {
            "prompt": text,
            "metadata": {
                "call_id": self.current_call_id,
                "from_call": True
            }
        }
        
        try:
            response = requests.post(endpoint, json=payload, timeout=10)
            
            if response.status_code in [200, 202]:
                logger.info(f"Text sent to backend: {text[:50]}...")
                return True
            else:
                logger.error(f"Failed to send text: {response.status_code}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"Error sending text to backend: {e}")
            return False


# Example usage functions
def simulate_facetime_call():
    """Simulate a FaceTime call being initiated by Agent-S."""
    import time
    
    # Initialize the integration
    call_integration = CallIntegration()
    
    # Check initial status
    status = call_integration.get_call_status()
    print(f"Initial call system status: {status}")
    
    # Simulate detecting a FaceTime call
    print("\n📱 FaceTime call detected! Notifying backend...")
    
    # Notify backend that call has started
    success = call_integration.notify_call_started(
        caller="+1-555-0123",  # Example phone number
        metadata={
            "call_type": "facetime",
            "initiated_by": "agent_s",
            "timestamp": time.time()
        }
    )
    
    if success:
        print("✅ Backend notified successfully! Call session active.")
        
        # Simulate call duration
        print("\n📞 Call in progress...")
        time.sleep(3)
        
        # During the call, Agent-S might send transcribed text
        call_integration.send_text_to_backend("Hello, this is a test message from the call.")
        
        # Simulate call ending
        print("\n📱 FaceTime call ended. Notifying backend...")
        call_integration.notify_call_ended()
        
        print("✅ Call session ended successfully.")
    else:
        print("❌ Failed to notify backend of call start.")
    
    # Check final status
    final_status = call_integration.get_call_status()
    print(f"\nFinal call system status: {status}")


if __name__ == "__main__":
    import time
    
    # Run the simulation
    simulate_facetime_call()
