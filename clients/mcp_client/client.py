# Import necessary libraries
import asyncio  # For handling asynchronous operations
import os       # For environment variable access
import sys      # For system-specific parameters and functions
from typing import Optional
from contextlib import AsyncExitStack

# Import MCP client components
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Import Google's Gen AI SDK
from google import genai
from google.genai import types
from google.genai.types import Tool, FunctionDeclaration, GenerateContentConfig

from dotenv import load_dotenv

# Rich for CLI styling
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.spinner import Spinner

# Load environment variables from .env file
load_dotenv()
console = Console()

import pyfiglet
from rich.console import Console

console = Console()

def print_ascii_banner(text: str):
    """Display a large ASCII banner."""
    ascii_banner = pyfiglet.figlet_format(text)
    console.print(f"[bold cyan]{ascii_banner}[/bold cyan]")


class MCPClient:
    def __init__(self):
        """Initialize the MCP client and configure the Gemini API."""
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()

        # Retrieve the Gemini API key from environment variables
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            console.print("[bold red]Error:[/bold red] GEMINI_API_KEY not found. Please add it to your .env file.")
            sys.exit(1)

        # Configure the Gemini AI client
        self.genai_client = genai.Client(api_key=gemini_api_key)

    async def connect_to_server(self, server_script_path: str):
        """Connect to the MCP server and list available tools."""

        # Determine whether the server script is Python or JavaScript
        command = "python" if server_script_path.endswith('.py') else "node"

        # Define server connection parameters
        server_params = StdioServerParameters(command=command, args=[server_script_path])

        # Establish communication with the MCP server
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport

        # Initialize the MCP client session
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        # Initialize the connection
        await self.session.initialize()

        # Get available tools from the server
        response = await self.session.list_tools()
        tools = response.tools

        console.print(Panel.fit(
            f"[bold green]Connected to server[/bold green]\nTools: [cyan]{', '.join([tool.name for tool in tools])}[/cyan]",
            border_style="green"
        ))

        # Convert MCP tools to Gemini format
        self.function_declarations = convert_mcp_tools_to_gemini(tools)

    async def process_query(self, query: str) -> str:
        """Process a user query using the Gemini API and execute tool calls if needed."""

        # Format user input for Gemini
        user_prompt_content = types.Content(
            role='user',
            parts=[types.Part.from_text(text=query)]
        )

        # Send query to Gemini with available tools
        with console.status("[bold cyan]Processing your request...[/bold cyan]", spinner="dots"):
            response = self.genai_client.models.generate_content(
                model='gemini-2.0-flash-001',
                contents=[user_prompt_content],
                config=GenerateContentConfig(
                    tools=self.function_declarations,
                ),
            )

        final_text = []

        # Process Gemini's response
        for candidate in response.candidates:
            if candidate.content.parts:
                for part in candidate.content.parts:
                    if isinstance(part, types.Part):
                        if part.function_call:
                            # Execute the requested tool
                            tool_name = part.function_call.name
                            tool_args = part.function_call.args

                            console.print(f"[yellow][Tool Call][/yellow] {tool_name} with args {tool_args}")

                            # Execute the tool via MCP
                            try:
                                result = await self.session.call_tool(tool_name, tool_args)
                                function_response = {"result": result.content}
                            except Exception as e:
                                function_response = {"error": str(e)}

                            # Format response for Gemini
                            function_response_part = types.Part.from_function_response(
                                name=tool_name,
                                response=function_response
                            )

                            function_response_content = types.Content(
                                role='tool',
                                parts=[function_response_part]
                            )

                            # Send tool result back to Gemini
                            response = self.genai_client.models.generate_content(
                                model='gemini-2.0-flash-001',
                                contents=[
                                    user_prompt_content,
                                    part,
                                    function_response_content,
                                ],
                                config=GenerateContentConfig(
                                    tools=self.function_declarations,
                                ),
                            )

                            text_part = getattr(response.candidates[0].content.parts[0], "text", None)
                            if text_part is not None:
                                final_text.append(text_part)
                        else:
                            text_part = getattr(part, "text", None)
                            if text_part is not None:
                                final_text.append(text_part)

        return "\n".join(final_text)

    async def chat_loop(self):
        """Run an interactive chat session with the user."""
        print_ascii_banner("MCPLink")
        console.print(Panel.fit("🤖 [bold cyan]MCP Client Started![/bold cyan]\nType 'quit' to exit", border_style="cyan"))

        while True:
            query = Prompt.ask("[bold green]Query[/bold green]")
            if query.lower() == 'quit':
                console.print("[bold red]Goodbye![/bold red]")
                break

            response = await self.process_query(query)

            # If Gemini's output looks like code, highlight it
            if "def " in response or "import " in response:
                syntax = Syntax(response, "python", theme="monokai", line_numbers=True)
                console.print(Panel(syntax, title="[bold blue]Gemini Response[/bold blue]", border_style="blue"))
            else:
                console.print(Panel(response, title="[bold blue]Gemini Response[/bold blue]", border_style="blue"))

    async def cleanup(self):
        """Clean up resources before exiting."""
        await self.exit_stack.aclose()


def clean_schema(schema):
    """Remove 'title' fields from JSON schema for Gemini compatibility."""
    if isinstance(schema, dict):
        schema.pop("title", None)

        if "properties" in schema and isinstance(schema["properties"], dict):
            for key in schema["properties"]:
                schema["properties"][key] = clean_schema(schema["properties"][key])

    return schema


def convert_mcp_tools_to_gemini(mcp_tools):
    """Convert MCP tool definitions to Gemini API format."""
    gemini_tools = []

    for tool in mcp_tools:
        parameters = clean_schema(tool.inputSchema)

        function_declaration = FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=parameters
        )

        gemini_tool = Tool(function_declarations=[function_declaration])
        gemini_tools.append(gemini_tool)

    return gemini_tools


async def main():
    """Main function to start the MCP client."""
    if len(sys.argv) < 2:
        console.print("[bold red]Usage:[/bold red] python client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
