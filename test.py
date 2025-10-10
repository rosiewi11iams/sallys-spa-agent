API_ENDPOINT = "https://hy81wz6jqc.execute-api.us-east-1.amazonaws.com/chat"
s3_bucket = "spa-services-d9cd4dd2"

import requests
import json

def chat(message, session_id="test-session"):
    response = requests.post(
        API_ENDPOINT,
        json={
            "message": message,
            "session_id": session_id
        }
    )
    return response.json()

if __name__ == "__main__":
    print("🧖‍♀️ Sally's Spa Chat (type 'quit' to exit)\n")
    
    session_id = "local-test"
    
    while True:
        user_input = input("You: ").strip()
        
        if user_input.lower() in ['quit', 'exit']:
            break
        
        if not user_input:
            continue
        
        try:
            result = chat(user_input, session_id)
            if 'message' in result:
                print(f"\nSpa: {result['message']}\n")
            else:
                print(f"\nFull response: {result}\n")
        except Exception as e:
            print(f"Error: {e}\n")
