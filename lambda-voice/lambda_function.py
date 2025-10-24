"""
Sally's Spa - Voice Lambda Function

This Lambda function handles phone calls via Twilio and uses Claude AI to provide
an intelligent voice receptionist for the spa. It integrates with the MCP Lambda
to access spa service information and maintains conversation history in DynamoDB.

Flow:
1. Twilio receives a phone call and sends a webhook to this Lambda
2. Lambda generates TwiML (Twilio Markup Language) to control the call
3. User speaks → Twilio transcribes → Lambda gets text
4. Lambda sends text to Claude AI for intelligent response
5. Claude may use tools (via MCP Lambda) to look up services
6. Lambda sends response back as TwiML for Twilio to speak
"""

import json  # For parsing and creating JSON data
import os  # For reading environment variables (API keys, etc.)
import boto3  # AWS SDK - used to interact with other AWS services
from anthropic import Anthropic  # Claude AI SDK for natural language processing
from urllib.parse import parse_qs  # For parsing form data from Twilio
import base64  # For decoding base64-encoded request bodies from API Gateway

# ============================================================================
# INITIALIZE AWS AND API CLIENTS
# ============================================================================
# These clients allow us to talk to other services

# Lambda client - allows this function to invoke the MCP Lambda function
lambda_client = boto3.client('lambda')

# DynamoDB resource - allows us to save/load conversation history from database
dynamodb = boto3.resource('dynamodb')

# Anthropic client - allows us to send messages to Claude AI
# The API key is stored as an environment variable for security
anthropic_client = Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

# ============================================================================
# CONFIGURATION FROM ENVIRONMENT VARIABLES
# ============================================================================
# These values are set by Terraform when deploying the Lambda function

# Name of the MCP Lambda function that provides spa service tools
MCP_LAMBDA_NAME = os.environ['MCP_LAMBDA_NAME']

# Name of the DynamoDB table where we store conversation history
# Defaults to 'spa-conversations' if not set
CONVERSATIONS_TABLE = os.environ.get('CONVERSATIONS_TABLE', 'spa-conversations')

# ============================================================================
# DATABASE FUNCTIONS - Conversation History
# ============================================================================

def get_conversation_history(session_id: str) -> list:
    """
    Retrieve previous messages from this phone conversation.

    Args:
        session_id: Unique identifier for this call (Twilio's CallSid)

    Returns:
        List of previous messages in the conversation, or empty list if this
        is a new conversation or if there's an error

    How it works:
        - Each phone call has a unique CallSid from Twilio
        - We use this as the session_id to look up past messages
        - This allows Claude to remember context from earlier in the call
    """
    try:
        # Connect to the conversations table in DynamoDB
        table = dynamodb.Table(CONVERSATIONS_TABLE)

        # Look up this specific conversation by session_id
        response = table.get_item(Key={'session_id': session_id})

        # Extract the messages array, return empty list if not found
        return response.get('Item', {}).get('messages', [])
    except:
        # If anything goes wrong, just start with no history
        return []

def save_conversation_history(session_id: str, messages: list):
    """
    Save the conversation messages to the database for later retrieval.

    Args:
        session_id: Unique identifier for this call
        messages: List of all messages in the conversation so far

    Why we do this:
        - Allows Claude to remember what was said earlier in the call
        - Example: User asks "What's the price?" then "How long does it take?"
          Claude needs to remember which service they were asking about
    """
    try:
        # Connect to the conversations table
        table = dynamodb.Table(CONVERSATIONS_TABLE)

        # Save (or overwrite) the conversation with updated messages
        table.put_item(Item={
            'session_id': session_id,
            'messages': messages
        })
    except Exception as e:
        # Log error but don't crash - conversation can continue without history
        print(f"Error saving conversation: {e}")

# ============================================================================
# MCP LAMBDA INTEGRATION - Business Logic Tools
# ============================================================================
# These functions communicate with the MCP Lambda, which provides tools for
# looking up spa services, prices, and availability

def call_mcp_tool(tool_name: str, arguments: dict = None) -> str:
    """
    Execute a specific tool by calling the MCP Lambda function.

    Args:
        tool_name: Name of the tool to execute (e.g., 'get_services', 'search_by_price')
        arguments: Dictionary of parameters for the tool (e.g., {'category': 'Facial'})

    Returns:
        String result from the tool (e.g., list of services, search results)

    How it works:
        1. Package the tool name and arguments into a JSON payload
        2. Invoke the MCP Lambda function (another Lambda that has the business logic)
        3. The MCP Lambda reads from S3, processes the request, returns results
        4. We extract and return the result string

    Example:
        call_mcp_tool('get_services', {'category': 'Facial'})
        -> Returns JSON string of all facial services
    """
    # Create the request payload for the MCP Lambda
    payload = {
        'body': json.dumps({
            'tool_name': tool_name,
            'arguments': arguments or {}
        })
    }

    # Invoke the MCP Lambda function and wait for response
    # 'RequestResponse' means we wait for the result (synchronous call)
    response = lambda_client.invoke(
        FunctionName=MCP_LAMBDA_NAME,
        InvocationType='RequestResponse',
        Payload=json.dumps(payload)
    )

    # Parse the response - Lambda returns nested JSON
    result = json.loads(response['Payload'].read())  # Read the response stream
    body = json.loads(result.get('body', '{}'))  # Extract the body
    return body.get('result', '')  # Return the actual result string

def get_available_tools() -> list:
    """
    Get the list of all tools that the MCP Lambda provides.

    Returns:
        List of tool definitions, each with:
        - name: The tool's identifier
        - description: What the tool does
        - parameters: What inputs it needs

    Why we need this:
        - Claude AI needs to know what tools are available
        - Each tool definition tells Claude when and how to use it
        - Example: Claude sees "search_by_price" tool and knows it can
          help when a customer asks "What's under $100?"
    """
    # Create request to list all available tools
    payload = {
        'body': json.dumps({'tool_name': 'list_tools'})
    }

    # Call the MCP Lambda
    response = lambda_client.invoke(
        FunctionName=MCP_LAMBDA_NAME,
        InvocationType='RequestResponse',
        Payload=json.dumps(payload)
    )

    # Parse and return the list of tools
    result = json.loads(response['Payload'].read())
    body = json.loads(result.get('body', '{}'))
    return body.get('tools', [])

def format_tools_for_claude(tools: list) -> list:
    """
    Convert MCP tool definitions into the format that Claude's API expects.

    Args:
        tools: List of tools from MCP Lambda (our custom format)

    Returns:
        List of tools in Claude's required format (with input_schema)

    Why this is needed:
        - MCP Lambda returns tools in a simple format
        - Claude's API expects a specific JSON schema format
        - This function translates between the two formats

    Example transformation:
        MCP format:
        {
            'name': 'search_by_price',
            'description': 'Find services under a price',
            'parameters': {'max_price': 'Maximum price (number)'}
        }

        Claude format:
        {
            'name': 'search_by_price',
            'description': 'Find services under a price',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'max_price': {'type': 'number', 'description': '...'}
                },
                'required': ['max_price']
            }
        }
    """
    claude_tools = []

    # Convert each tool to Claude's format
    for tool in tools:
        properties = {}
        required = []

        # Convert each parameter
        for param_name, param_desc in tool.get('parameters', {}).items():
            # Try to infer the parameter type from description
            param_type = 'string'  # Default to string
            if 'number' in param_desc.lower():
                param_type = 'number'

            # Add to properties dict
            properties[param_name] = {
                'type': param_type,
                'description': param_desc
            }
            # All parameters are required
            required.append(param_name)

        # Build the tool definition in Claude's format
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

# ============================================================================
# CLAUDE AI CONVERSATION - Main Intelligence
# ============================================================================

def chat_with_claude(user_message: str, session_id: str) -> str:
    """
    Send the user's message to Claude AI and get an intelligent response.

    This is the core function that orchestrates the entire conversation flow:
    1. Get conversation history to provide context
    2. Get available tools so Claude knows what information it can access
    3. Send message to Claude
    4. If Claude wants to use a tool, execute it and send results back
    5. Return Claude's final response

    Args:
        user_message: What the caller said (transcribed by Twilio)
        session_id: Unique call ID to track conversation context

    Returns:
        Claude's response text to be spoken back to the caller

    Example flow:
        User: "What facials do you have?"
        -> Claude decides to use 'get_services' tool with category='Facial'
        -> We call MCP Lambda to get the service list
        -> Send results back to Claude
        -> Claude: "We have several great facials! The Hydrating Facial is..."
    """

    # STEP 1: Get conversation history for context
    # This lets Claude remember what was discussed earlier in the call
    history = get_conversation_history(session_id)

    # STEP 2: Get available tools and format for Claude
    # These are the "functions" Claude can use to look up spa information
    tools = get_available_tools()
    claude_tools = format_tools_for_claude(tools)

    # STEP 3: Build the message list for Claude
    # Format: [previous messages..., new user message]
    messages = history + [{'role': 'user', 'content': user_message}]

    # STEP 4: Define Claude's personality and instructions
    # This system prompt tells Claude how to behave on phone calls
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

    # STEP 5: Call Claude AI API
    response = anthropic_client.messages.create(
        model="claude-3-5-haiku-20241022",  # Fast model for real-time responses
        max_tokens=150,  # Reduced for faster responses (was 256)
        system=system_prompt,  # Claude's personality and instructions
        messages=messages,  # The conversation history + new message
        tools=claude_tools if claude_tools else None  # Available tools
    )

    # STEP 6: Tool Use Loop
    # Claude might want to use tools to look up information before responding.
    # We loop until Claude has all the info it needs and gives a final answer.
    final_text = ""

    while True:
        # Process Claude's response
        assistant_content = []
        needs_tool_result = False

        # Check each part of Claude's response
        for content_block in response.content:
            # Save the content block for conversation history
            assistant_content.append(content_block.model_dump())

            if content_block.type == 'text':
                # This is text Claude wants to say to the user
                final_text += content_block.text

            elif content_block.type == 'tool_use':
                # Claude wants to use a tool to get information
                # Example: Claude decides it needs to call 'get_services'
                needs_tool_result = True

        # Add Claude's response to conversation history
        messages.append({'role': 'assistant', 'content': assistant_content})

        # STEP 7: Execute any tools Claude requested
        if needs_tool_result:
            tool_results = []

            # Execute each tool Claude wants to use
            for content_block in response.content:
                if content_block.type == 'tool_use':
                    # Call the MCP Lambda to execute this tool
                    # Example: content_block.name = 'get_services'
                    #          content_block.input = {'category': 'Facial'}
                    tool_result = call_mcp_tool(content_block.name, content_block.input)

                    # Package the result to send back to Claude
                    tool_results.append({
                        'type': 'tool_result',
                        'tool_use_id': content_block.id,  # Match request to response
                        'content': tool_result
                    })

            # Add tool results to conversation (as a "user" message containing data)
            messages.append({'role': 'user', 'content': tool_results})

            # STEP 8: Call Claude again with the tool results
            # Now Claude has the information and can formulate a natural response
            response = anthropic_client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=150,  # Reduced for faster responses
                system=system_prompt,
                messages=messages,
                tools=claude_tools if claude_tools else None
            )
            # Loop continues - check if Claude needs more tools or has final answer
        else:
            # Claude has everything it needs and gave a final text response
            break

    # STEP 9: Save the conversation for next time
    # Only keep the new messages from this interaction
    new_messages = messages[len(history):]
    updated_history = history + new_messages

    # Store only recent messages to keep voice conversations lightweight
    # IMPORTANT: We need to be careful not to break tool_use/tool_result pairs
    # when trimming. We'll keep complete user/assistant exchanges.
    trimmed_history = trim_conversation_history(updated_history, max_pairs=5)
    save_conversation_history(session_id, trimmed_history)

    # Return Claude's response to be spoken to the caller
    return final_text

def trim_conversation_history(messages: list, max_pairs: int = 5) -> list:
    """
    Trim conversation history while preserving complete user/assistant exchanges.

    Claude's conversation format alternates:
    - user message
    - assistant message (may contain tool_use)
    - user message (may contain tool_result if previous had tool_use)
    - assistant message (final response after getting tool results)
    - ... and so on

    We need to keep complete exchanges to avoid orphaned tool_result blocks.

    Args:
        messages: Full conversation history
        max_pairs: Maximum number of complete user/assistant exchanges to keep

    Returns:
        Trimmed conversation history with complete exchanges
    """
    if len(messages) <= max_pairs * 2:
        return messages

    # Start from the end and work backwards, keeping complete pairs
    # We want to keep the most recent max_pairs exchanges
    # Each "exchange" is typically 2 messages (user + assistant)
    # But can be 4 if tools are involved (user, assistant with tool_use, user with tool_result, assistant with final response)

    # Simple approach: keep last (max_pairs * 4) messages to be safe
    # This ensures we don't break any tool use/result chains
    keep_count = max_pairs * 4
    return messages[-keep_count:]

# ============================================================================
# TWILIO TWIML GENERATION - Phone Call Control
# ============================================================================

def generate_twiml(message: str, next_action: str = 'gather') -> str:
    """
    Generate TwiML (Twilio Markup Language) to control the phone call.

    TwiML is XML that tells Twilio what to do on a phone call:
    - What to say (text-to-speech)
    - Whether to listen for user input
    - Whether to hang up
    - Where to send the next request

    Args:
        message: The text to speak to the caller
        next_action: What to do after speaking
                    'gather' = listen for user response (default)
                    'hangup' = end the call

    Returns:
        XML string that Twilio will execute

    Example output:
        <?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="Polly.Joanna">Hello! How can I help?</Say>
            <Gather input="speech" action="/voice/process" method="POST" speechTimeout="2" language="en-US"/>
            <Redirect>/voice/gather</Redirect>
        </Response>
    """
    # Start the TwiML response
    twiml = '<?xml version="1.0" encoding="UTF-8"?><Response>'

    # Speak the message using Amazon Polly's "Joanna" voice
    twiml += f'<Say voice="Polly.Joanna">{message}</Say>'

    if next_action == 'gather':
        # Listen for the caller to speak
        # When they finish, POST the transcription to /voice/process
        twiml += '<Gather input="speech" action="/voice/process" method="POST" '
        twiml += 'speechTimeout="2" language="en-US"/>'

        # If no input after timeout, redirect to /voice/gather to try again
        twiml += '<Redirect>/voice/gather</Redirect>'

    elif next_action == 'hangup':
        # End the phone call
        twiml += '<Hangup/>'

    # Close the response
    twiml += '</Response>'
    return twiml

# ============================================================================
# LAMBDA HANDLER - Main Entry Point
# ============================================================================

def lambda_handler(event, context):
    """
    Main entry point for the Lambda function.

    This function is called by AWS Lambda whenever a request comes in.
    Twilio sends webhooks (HTTP requests) to this Lambda via API Gateway.

    Request Flow:
    1. Twilio makes HTTP request → API Gateway → This Lambda
    2. We parse the request to determine what Twilio is asking for
    3. We route to the appropriate handler based on the URL path
    4. We return TwiML to tell Twilio what to do next

    Args:
        event: Contains request data (path, body, headers, etc.)
        context: Lambda runtime information (not used here)

    Returns:
        HTTP response with TwiML XML body
    """

    # Log the incoming request for debugging
    print(f"Event: {json.dumps(event)}")

    # Extract the URL path (e.g., '/voice/incoming', '/voice/process')
    path = event.get('path', '/')
    http_method = event.get('httpMethod', 'GET')

    # Parse form data from Twilio
    # Twilio sends data as URL-encoded form data, not JSON
    body = event.get('body', '')

    # IMPORTANT: API Gateway may base64-encode the body
    # Check if it's encoded and decode it first
    if event.get('isBase64Encoded', False):
        body = base64.b64decode(body).decode('utf-8')

    if body:
        # parse_qs returns dict with arrays as values
        params = parse_qs(body)
        # Get first value from each array (Twilio only sends one value per field)
        params = {k: v[0] if isinstance(v, list) else v for k, v in params.items()}
    else:
        params = {}

    # Get the unique call identifier from Twilio
    # We use this as the session_id to track conversation history
    call_sid = params.get('CallSid', 'default')

    # ========================================================================
    # ROUTE 1: Incoming Call
    # ========================================================================
    # Twilio calls this when someone first dials the spa's phone number
    if path == '/voice/incoming' or path == '/':
        # Greet the caller and ask how we can help
        twiml = generate_twiml(
            "Hello! Welcome to Sally's Spa. How can I help you today?",
            next_action='gather'  # Listen for their response
        )

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/xml'},
            'body': twiml
        }

    # ========================================================================
    # ROUTE 2: No Input Received (Timeout)
    # ========================================================================
    # Twilio redirects here if the caller doesn't say anything
    elif path == '/voice/gather':
        # Politely prompt them again
        twiml = generate_twiml(
            "I didn't catch that. Please tell me what you're looking for.",
            next_action='gather'  # Give them another chance to speak
        )

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/xml'},
            'body': twiml
        }

    # ========================================================================
    # ROUTE 3: Process User Speech (Main Intelligence)
    # ========================================================================
    # Twilio posts here after transcribing what the caller said
    elif path == '/voice/process':
        # Get the transcribed speech from Twilio
        # Example: "What facials do you have?"
        speech_result = params.get('SpeechResult', '')

        print(f"User said: {speech_result}")

        if speech_result:
            try:
                # Send the user's message to Claude AI and get a response
                # This is where the magic happens - Claude uses tools to look up
                # services and generates a natural, helpful response
                ai_response = chat_with_claude(speech_result, call_sid)
                print(f"AI response: {ai_response}")

                # Check if the caller is saying goodbye
                lower_speech = speech_result.lower()
                if any(word in lower_speech for word in ['bye', 'goodbye', 'thanks', 'thank you', 'that\'s all']):
                    # End the call gracefully
                    twiml = generate_twiml(
                        f"{ai_response} Thank you for calling Sally's Spa. Have a wonderful day!",
                        next_action='hangup'
                    )
                else:
                    # Continue the conversation - wait for next question
                    twiml = generate_twiml(ai_response, next_action='gather')

            except Exception as e:
                # Something went wrong (Claude API error, Lambda timeout, etc.)
                print(f"Error: {e}")
                twiml = generate_twiml(
                    "I'm sorry, I'm having trouble right now. Please try again.",
                    next_action='gather'
                )
        else:
            # Twilio sent empty speech result (shouldn't normally happen)
            twiml = generate_twiml(
                "I didn't hear anything. What can I help you with?",
                next_action='gather'
            )

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/xml'},
            'body': twiml
        }

    # ========================================================================
    # ROUTE 4: Unknown Path
    # ========================================================================
    else:
        # Someone accessed an invalid URL
        return {
            'statusCode': 404,
            'headers': {'Content-Type': 'text/plain'},
            'body': 'Not Found'
        }
