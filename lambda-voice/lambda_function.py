import json
import os
import boto3
from anthropic import Anthropic
from urllib.parse import parse_qs

# Initialize clients
lambda_client = boto3.client('lambda')
dynamodb = boto3.resource('dynamodb')
anthropic_client = Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

MCP_LAMBDA_NAME = os.environ['MCP_LAMBDA_NAME']
CONVERSATIONS_TABLE = os.environ.get('CONVERSATIONS_TABLE', 'spa-conversations')

def get_conversation_history(session_id: str) -> list:
    """Get conversation history from DynamoDB"""
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        response = table.get_item(Key={'session_id': session_id})
        return response.get('Item', {}).get('messages', [])
    except:
        return []

def save_conversation_history(session_id: str, messages: list):
    """Save conversation history to DynamoDB"""
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        table.put_item(Item={
            'session_id': session_id,
            'messages': messages
        })
    except Exception as e:
        print(f"Error saving conversation: {e}")

def call_mcp_tool(tool_name: str, arguments: dict = None) -> str:
    """Call the MCP Lambda function"""
    payload = {
        'body': json.dumps({
            'tool_name': tool_name,
            'arguments': arguments or {}
        })
    }

    response = lambda_client.invoke(
        FunctionName=MCP_LAMBDA_NAME,
        InvocationType='RequestResponse',
        Payload=json.dumps(payload)
    )

    result = json.loads(response['Payload'].read())
    body = json.loads(result.get('body', '{}'))
    return body.get('result', '')

def get_available_tools() -> list:
    """Get list of available tools from MCP Lambda"""
    payload = {
        'body': json.dumps({'tool_name': 'list_tools'})
    }

    response = lambda_client.invoke(
        FunctionName=MCP_LAMBDA_NAME,
        InvocationType='RequestResponse',
        Payload=json.dumps(payload)
    )

    result = json.loads(response['Payload'].read())
    body = json.loads(result.get('body', '{}'))
    return body.get('tools', [])

def format_tools_for_claude(tools: list) -> list:
    """Format tools for Claude's API"""
    claude_tools = []

    for tool in tools:
        properties = {}
        required = []

        for param_name, param_desc in tool.get('parameters', {}).items():
            param_type = 'string'
            if 'number' in param_desc.lower():
                param_type = 'number'

            properties[param_name] = {
                'type': param_type,
                'description': param_desc
            }
            required.append(param_name)

        claude_tools.append({
            'name': tool['name'],
            'description': tool['description'],
            'input_schema': {
                'type': 'object',
                'properties': properties,
                'required': required
            }
        })

    return claude_tools

def chat_with_claude(user_message: str, session_id: str) -> str:
    """Chat with Claude using MCP tools (optimized for voice)"""

    # Get conversation history
    history = get_conversation_history(session_id)

    # Get available tools
    tools = get_available_tools()
    claude_tools = format_tools_for_claude(tools)

    # Build messages for Claude
    messages = history + [{'role': 'user', 'content': user_message}]

    # System prompt optimized for phone conversations
    system_prompt = """You are Sally, a friendly spa receptionist at "Sally's Spa".

Your role:
- Help customers learn about our spa services over the phone
- Answer questions about prices and duration
- Make recommendations based on their interests
- Be warm, professional, and conversational

IMPORTANT for phone calls:
- Keep responses SHORT and NATURAL (1-2 sentences max)
- Speak conversationally, not in bullet points or lists
- Don't use special characters, emojis, or formatting
- Don't say prices as "$50" - say "fifty dollars"
- Ask follow-up questions to keep the conversation going
- If someone wants to book, tell them to visit our website or call back

Use the tools available to get accurate service information."""

    # Call Claude
    response = anthropic_client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=256,
        system=system_prompt,
        messages=messages,
        tools=claude_tools if claude_tools else None
    )

    # Process response with tool use loop
    final_text = ""

    while True:
        # Process current response
        assistant_content = []
        needs_tool_result = False

        for content_block in response.content:
            assistant_content.append(content_block.model_dump())

            if content_block.type == 'text':
                final_text += content_block.text
            elif content_block.type == 'tool_use':
                needs_tool_result = True

        # Add assistant message
        messages.append({'role': 'assistant', 'content': assistant_content})

        # If tools were used, execute them and continue
        if needs_tool_result:
            tool_results = []
            for content_block in response.content:
                if content_block.type == 'tool_use':
                    tool_result = call_mcp_tool(content_block.name, content_block.input)
                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': content_block.id,
                        'content': tool_result
                    })

            # Add tool results message
            messages.append({'role': 'user', 'content': tool_results})

            # Get next response from Claude
            response = anthropic_client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=256,
                system=system_prompt,
                messages=messages,
                tools=claude_tools if claude_tools else None
            )
        else:
            # No more tools needed, exit loop
            break

    # Save conversation history (keep last 10 messages for voice)
    new_messages = messages[len(history):]
    updated_history = history + new_messages
    save_conversation_history(session_id, updated_history[-10:])

    return final_text

def generate_twiml(message: str, next_action: str = 'gather') -> str:
    """Generate TwiML response"""
    twiml = '<?xml version="1.0" encoding="UTF-8"?><Response>'

    # Say the message
    twiml += f'<Say voice="Polly.Joanna">{message}</Say>'

    if next_action == 'gather':
        # Gather speech input
        twiml += '<Gather input="speech" action="/voice/process" method="POST" '
        twiml += 'speechTimeout="2" language="en-US"/>'
        # If no input, redirect
        twiml += '<Redirect>/voice/gather</Redirect>'
    elif next_action == 'hangup':
        twiml += '<Hangup/>'

    twiml += '</Response>'
    return twiml

def lambda_handler(event, context):
    """Handle Twilio voice webhooks"""

    print(f"Event: {json.dumps(event)}")

    # Parse request path
    path = event.get('path', '/')
    http_method = event.get('httpMethod', 'GET')

    # Parse Twilio form data
    body = event.get('body', '')
    if body:
        params = parse_qs(body)
        # Twilio sends arrays, get first value
        params = {k: v[0] if isinstance(v, list) else v for k, v in params.items()}
    else:
        params = {}

    call_sid = params.get('CallSid', 'default')

    # Route based on path
    if path == '/voice/incoming' or path == '/':
        # Incoming call - welcome message
        twiml = generate_twiml(
            "Hello! Welcome to Sally's Spa. How can I help you today?",
            next_action='gather'
        )

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/xml'},
            'body': twiml
        }

    elif path == '/voice/gather':
        # No input received, prompt again
        twiml = generate_twiml(
            "I didn't catch that. Please tell me what you're looking for.",
            next_action='gather'
        )

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/xml'},
            'body': twiml
        }

    elif path == '/voice/process':
        # Process speech input
        speech_result = params.get('SpeechResult', '')

        print(f"User said: {speech_result}")

        if speech_result:
            try:
                # Get AI response
                ai_response = chat_with_claude(speech_result, call_sid)
                print(f"AI response: {ai_response}")

                # Check for goodbye keywords
                lower_speech = speech_result.lower()
                if any(word in lower_speech for word in ['bye', 'goodbye', 'thanks', 'thank you', 'that\'s all']):
                    twiml = generate_twiml(
                        f"{ai_response} Thank you for calling Sally's Spa. Have a wonderful day!",
                        next_action='hangup'
                    )
                else:
                    twiml = generate_twiml(ai_response, next_action='gather')

            except Exception as e:
                print(f"Error: {e}")
                twiml = generate_twiml(
                    "I'm sorry, I'm having trouble right now. Please try again.",
                    next_action='gather'
                )
        else:
            twiml = generate_twiml(
                "I didn't hear anything. What can I help you with?",
                next_action='gather'
            )

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/xml'},
            'body': twiml
        }

    else:
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'text/plain'},
            'body': 'Not Found'
        }
