import json
import os
import boto3
from typing import List, Dict

s3_client = boto3.client('s3')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'your-spa-bucket')

def load_services() -> List[dict]:
    """Load services from S3"""
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key='services.json')
        data = json.loads(response['Body'].read())
        return data['services']
    except Exception as e:
        print(f"Error loading services: {e}")
        return []

def get_all_services() -> str:
    """Get the complete list of spa services"""
    services = load_services()
    
    if not services:
        return "Sorry, I couldn't load our services right now."
    
    result = "✨ SPA SERVICES ✨\n\n"
    for service in services:
        result += f"• {service['name']} - ${service['price']}\n"
        result += f"  Duration: {service['duration']}\n\n"
    
    return result

def get_service_info(service_name: str) -> str:
    """Get details about a specific service"""
    services = load_services()
    
    # Exact match
    for service in services:
        if service['name'].lower() == service_name.lower():
            return (f"{service['name']}\n"
                   f"Price: ${service['price']}\n"
                   f"Duration: {service['duration']}")
    
    # Partial match
    matches = [s for s in services if service_name.lower() in s['name'].lower()]
    if matches:
        result = "Did you mean:\n"
        for s in matches:
            result += f"• {s['name']} (${s['price']})\n"
        return result
    
    return f"Sorry, I couldn't find '{service_name}' in our services."

def search_by_price(max_price: float) -> str:
    """Find services under a specific price"""
    services = load_services()
    
    affordable = [s for s in services if s['price'] <= max_price]
    
    if not affordable:
        return f"Sorry, we don't have services under ${max_price}."
    
    result = f"Services under ${max_price}:\n\n"
    for service in affordable:
        result += f"• {service['name']} - ${service['price']} ({service['duration']})\n"
    
    return result

def get_service_categories() -> str:
    """Get services organized by type"""
    services = load_services()
    
    # Simple categorization
    nails = [s for s in services if 'nail' in s['name'].lower() or s['name'].lower() in ['manicure', 'pedicure']]
    hair = [s for s in services if 'hair' in s['name'].lower() or 'blowout' in s['name'].lower()]
    spa = [s for s in services if s['name'].lower() in ['facial', 'massage']]
    
    result = "📋 SERVICES BY CATEGORY\n\n"
    
    if nails:
        result += "💅 NAIL SERVICES:\n"
        for s in nails:
            result += f"  • {s['name']} - ${s['price']}\n"
        result += "\n"
    
    if hair:
        result += "💇 HAIR SERVICES:\n"
        for s in hair:
            result += f"  • {s['name']} - ${s['price']}\n"
        result += "\n"
    
    if spa:
        result += "🧖 SPA TREATMENTS:\n"
        for s in spa:
            result += f"  • {s['name']} - ${s['price']}\n"
    
    return result

# Tool registry
TOOLS = {
    'get_all_services': {
        'function': get_all_services,
        'description': 'Get the complete list of spa services with prices and duration',
        'parameters': {}
    },
    'get_service_info': {
        'function': get_service_info,
        'description': 'Get details about a specific service',
        'parameters': {
            'service_name': 'string - Name of the service'
        }
    },
    'search_by_price': {
        'function': search_by_price,
        'description': 'Find services under a specific price',
        'parameters': {
            'max_price': 'number - Maximum price'
        }
    },
    'get_service_categories': {
        'function': get_service_categories,
        'description': 'Get services organized by category (nails, hair, spa treatments)',
        'parameters': {}
    }
}

def lambda_handler(event, context):
    """Handle MCP tool calls"""
    
    # Parse request
    body = json.loads(event.get('body', '{}'))
    tool_name = body.get('tool_name')
    arguments = body.get('arguments', {})
    
    # List available tools
    if tool_name == 'list_tools':
        return {
            'statusCode': 200,
            'body': json.dumps({
                'tools': [
                    {
                        'name': name,
                        'description': info['description'],
                        'parameters': info['parameters']
                    }
                    for name, info in TOOLS.items()
                ]
            })
        }
    
    # Execute tool
    if tool_name not in TOOLS:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': f'Unknown tool: {tool_name}'})
        }
    
    try:
        tool_func = TOOLS[tool_name]['function']
        result = tool_func(**arguments)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'result': result})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }