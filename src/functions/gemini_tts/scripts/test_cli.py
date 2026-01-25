import argparse
import requests
import json
import os

def main():
    parser = argparse.ArgumentParser(description="Test Gemini TTS Function")
    parser.add_argument("--text", type=str, required=True, help="Text to convert to speech")
    parser.add_argument("--key", type=str, default=os.getenv("GEMINI_API_KEY"), help="Gemini API Key")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash-preview-tts", help="Model name")
    parser.add_argument("--output", type=str, default="output.mp3", help="Output file path")
    parser.add_argument("--url", type=str, default="http://localhost:8080", help="Function URL")
    
    args = parser.parse_args()
    
    if not args.key:
        print("Error: Gemini API Key is required (pass --key or set GEMINI_API_KEY env var)")
        return

    payload = {
        "text": args.text,
        "model_name": args.model,
        "credentials": {
            "gemini": args.key
        }
    }
    
    print(f"Sending request to {args.url}...")
    try:
        response = requests.post(args.url, json=payload)
        
        if response.status_code == 200:
            with open(args.output, "wb") as f:
                f.write(response.content)
            print(f"Success! Audio saved to {args.output}")
        else:
            print(f"Error ({response.status_code}): {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    main()
