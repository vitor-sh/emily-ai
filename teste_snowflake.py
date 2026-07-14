from anthropic import AnthropicVertex

client = AnthropicVertex(region="global", project_id="project-160d2dff-27c7-4d00-b1f")
message = client.messages.create(
 max_tokens=1024,
 messages=[{"role": "user", "content": "Hello! Can you help me?"}],
 model="claude-sonnet-5"
)
print(message.content[0].text)