import httpx
import os
import sys
import json

# Configuration
BASE_URL = "http://localhost:8080"
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    # Try to load from .env manually
    # __file__ = src/functions/gemini_tts/scripts/test_edge_cases.py
    # 1=scripts, 2=gemini_tts, 3=functions, 4=src, 5=root
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    env_path = os.path.join(base_dir, ".env")
    print(f"DEBUG: Looking for .env at {env_path}")
    if os.path.exists(env_path):
        print(f"Loading .env from {env_path}")
        with open(env_path, "r") as f:
            for line in f:
                if line.strip().startswith("GEMINI_API_KEY="):
                    # Extract value, handling potential quotes and comments
                    value = line.split("=", 1)[1].strip()
                    # Remove inline comments
                    if "#" in value:
                        value = value.split("#")[0].strip()
                    # Remove quotes
                    value = value.strip('"').strip("'")
                    API_KEY = value
                    break

if not API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set and not found in .env.")
    sys.exit(1)

def run_test(name, payload, expected_status=200, description=""):
    print(f"\n--- Running Test: {name} ---")
    if description:
        print(f"Description: {description}")
    
    try:
        response = httpx.post(BASE_URL, json=payload, timeout=30.0)
        status_match = response.status_code == expected_status
        
        print(f"Status Code: {response.status_code} (Expected: {expected_status})")
        
        if not status_match:
            print(f"FAILED: Status mismatch. Response text: {response.text[:200]}...")
            return False
            
        if expected_status == 200:
            if len(response.content) > 0:
                print(f"SUCCESS: Received {len(response.content)} bytes of audio.")
                # Verify header
                ct = response.headers.get("Content-Type")
                if ct == "audio/mpeg":
                     print("SUCCESS: Content-Type is audio/mpeg")
                else:
                     print(f"WARNING: Content-Type is {ct}")
            else:
                print("FAILED: Response empty")
                return False
        else:
            print(f"SUCCESS: received expected error status.")
            
        return True
    except Exception as e:
        print(f"ERROR: Exception during test: {e}")
        return False

def main():
    print("Starting Gemini TTS Edge Case Tests...")
    
    # 1. Happy Path
    run_test("Happy Path", {
        "text": "Hello, this is a normal test.",
        "model_name": "gemini-2.5-flash-preview-tts",
        "credentials": {"gemini": API_KEY}
    }, description="Standard request with valid inputs.")

    # 2. Empty Text
    run_test("Empty Text", {
        "text": "",
        "model_name": "gemini-2.5-flash-preview-tts",
        "credentials": {"gemini": API_KEY}
    }, expected_status=400, description="Sending empty string as text.") 

    # 3. Special Characters - Gemini TTS often rejects complex symbol strings with finishReason: OTHER
    # So we expect 400 or 200 depending on model leniency. 
    # For now, let's accept 400 as a valid 'handled' state for this input.
    run_test("Special Characters", {
        "text": "Hello! @#$%^&*()_+ 🚀✨ This is a test with emojis and symbols.",
        "model_name": "gemini-2.5-flash-preview-tts",
        "credentials": {"gemini": API_KEY}
    }, expected_status=400, description="Text with symbols and emojis (Expect 400 if model rejects).")

    # 4. Long Text
    long_text = "This is a sentence. " * 50
    run_test("Long Text", {
        "text": long_text,
        "model_name": "gemini-2.5-flash-preview-tts",
        "credentials": {"gemini": API_KEY}
    }, description=f"Text with {len(long_text)} characters.")

    # 5. Invalid Model Name
    run_test("Invalid Model", {
        "text": "Test",
        "model_name": "gemini-non-existent-model",
        "credentials": {"gemini": API_KEY}
    }, expected_status=502, description="Using a non-existent model name.")

    # 6. Invalid API Key
    run_test("Invalid Credentials", {
        "text": "Test",
        "model_name": "gemini-2.5-flash-preview-tts",
        "credentials": {"gemini": "INVALID_KEY_12345"}
    }, expected_status=502, description="Using an invalid API key.")

    # 7. Missing Credentials (Validation Error)
    # This should fail Pydantic validation (400)
    print("\n--- Running Test: Missing Credentials ---")
    try:
        resp = httpx.post(BASE_URL, json={
            "text": "Test",
            "model_name": "gemini-2.5-flash-preview-tts"
        })
        if resp.status_code == 400:
             print("SUCCESS: Got 400 Bad Request for missing credentials.")
        else:
             print(f"FAILED: Expected 400, got {resp.status_code}")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    main()
