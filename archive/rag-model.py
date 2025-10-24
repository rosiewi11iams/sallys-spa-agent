# Import the Anthropic Python SDK to interact with Claude API
import anthropic

# Initialise the Anthropic client
# The API key is read from the ANTHROPIC_API_KEY environment variable
client = anthropic.Anthropic()

# Create a message by calling Claude Sonnet 4.5 model
# This sends a user query asking for renewable energy search terms
message = client.messages.create(
    model="claude-sonnet-4-5",  # Specify which Claude model to use
    max_tokens=1000,  # Set maximum length of the response (in tokens)
    system="You are a friendly receptionist at a spa.",
    messages=[
        {
            "role": "user",  # Indicates this is a message from the user
            "content": "What is the best facial for dry skin?"  # The actual question/prompt
        }
    ]
)

# Print the response content from Claude
print(message.content)
