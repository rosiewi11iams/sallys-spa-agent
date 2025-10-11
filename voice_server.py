from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
import os
from dotenv import load_dotenv
import json
import base64
import asyncio
from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation
from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface

load_dotenv()

app = FastAPI()

# Initialize ElevenLabs client
elevenlabs_client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

@app.get("/")
async def root():
    return {"message": "Sally's Spa Voice Agent is running!"}

@app.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Handle incoming Twilio voice call"""
    
    # Get the base URL for websocket connection
    host = request.headers.get("host")
    protocol = "wss" if "https" in str(request.url) else "ws"
    
    # Return TwiML to connect to our websocket
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{protocol}://{host}/media-stream" />
    </Connect>
</Response>"""
    
    return Response(content=twiml, media_type="application/xml")

@app.websocket("/media-stream")
async def media_stream_handler(websocket: WebSocket):
    """Handle the media stream between Twilio and ElevenLabs"""
    await websocket.accept()
    print("WebSocket connection established")
    
    stream_sid = None
    conversation = None
    
    try:
        # Create ElevenLabs conversation
        agent_id = os.getenv("ELEVENLABS_AGENT_ID")
        
        conversation = elevenlabs_client.conversational_ai.conversation.start_session(
            agent_id=agent_id
        )
        
        print(f"ElevenLabs conversation started: {conversation.conversation_id}")
        
        # Handle messages from Twilio
        async for message in websocket.iter_text():
            data = json.loads(message)
            
            if data["event"] == "start":
                stream_sid = data["start"]["streamSid"]
                print(f"Twilio stream started: {stream_sid}")
                
            elif data["event"] == "media":
                # Audio from caller (base64 encoded mulaw)
                payload = data["media"]["payload"]
                
                # Decode and send to ElevenLabs
                audio_bytes = base64.b64decode(payload)
                
                # Send audio to ElevenLabs conversation
                response_audio = await process_with_elevenlabs(
                    conversation, 
                    audio_bytes
                )
                
                # Send response back to Twilio
                if response_audio:
                    # Encode for Twilio (mulaw base64)
                    encoded_audio = base64.b64encode(response_audio).decode('utf-8')
                    
                    await websocket.send_json({
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {
                            "payload": encoded_audio
                        }
                    })
                
            elif data["event"] == "stop":
                print(f"Twilio stream stopped: {stream_sid}")
                break
                
    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"Error in media stream: {e}")
    finally:
        if conversation:
            # End the ElevenLabs conversation
            try:
                conversation.end_session()
            except:
                pass
        await websocket.close()

async def process_with_elevenlabs(conversation, audio_bytes):
    """Process audio with ElevenLabs and return response"""
    try:
        # Send audio to conversation and get response
        response = conversation.send_audio(audio_bytes)
        return response.audio if response else None
    except Exception as e:
        print(f"Error processing with ElevenLabs: {e}")
        return None

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5005))
    uvicorn.run(app, host="0.0.0.0", port=port)