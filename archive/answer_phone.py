from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse

app = Flask(__name__)

@app.route("/voice/incoming", methods=['GET', 'POST'])
def incoming_call():
    print("=== INCOMING CALL ===")  # Debug logging
    response = VoiceResponse()
    response.say("Hello! This is a test call.")
    return Response(str(response), mimetype='text/xml')

@app.route("/")
def home():
    return "Voice agent is running!"

if __name__ == "__main__":
    print("Starting Flask app on port 5005...")
    app.run(debug=True, port=5005, host='0.0.0.0')