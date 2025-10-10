import json
import os
import boto3
from anthropic import Anthropic

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

def chat_with_claude(user_message: str, session_id: str) -> dict:
    """Main chat function with Claude"""
    
    # Get conversation history
    history = get_conversation_history(session_id)
    
    # Get available tools
    tools = get_available_tools()
    claude_tools = format_tools_for_claude(tools)
    
    # Build messages for Claude
    messages = history + [{'role': 'user', 'content': user_message}]
    
    # System prompt
    system_prompt = """You are a friendly spa receptionist at "Serenity Spa".

Your role:
- Help customers learn about our spa services
- Answer questions about prices and duration
- Make recommendations based on their interests
- Be warm, professional, and helpful

Use the tools available to get accurate service information.
Keep responses conversational and concise."""
    
    # Call Claude
    response = anthropic_client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=1024,
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
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
                tools=claude_tools if claude_tools else None
            )
        else:
            # No more tools needed, exit loop
            break

    # Save conversation history (everything after the original history)
    new_messages = messages[len(history):]
    updated_history = history + new_messages
    save_conversation_history(session_id, updated_history[-20:])  # Keep last 20 messages
    
    return {
        'message': final_text,
        'session_id': session_id
    }

def lambda_handler(event, context):
    """Handle chat requests"""
    
    # Handle CORS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'POST, OPTIONS'
            },
            'body': ''
        }
    
    # Parse request
    try:
        body = json.loads(event.get('body', '{}'))
        user_message = body.get('message', '')
        session_id = body.get('session_id', 'default-session')
        
        if not user_message:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({'error': 'Message is required'})
            }
        
        # Get response
        result = chat_with_claude(user_message, session_id)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result)
        }
        
    except Exception as e:
        print(f"Error: {e}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'error': str(e)})
        }
