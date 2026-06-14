from langchain_core.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command


@tool(parse_docstring=True)
def display_widget(
    title: str,
    html_content: str,
    description: str,
    runtime: ToolRuntime,
    height: int = 500,
) -> Command:
    """Display an HTML visualization widget inline in the chat.

    Use this tool after receiving generated HTML from a sub-agent or after constructing HTML yourself. The widget is rendered directly in the chat interface for the user to see.

    Args:
        title: Title displayed above the visualization widget.
        html_content: Complete, self-contained HTML string to render. Must include all CSS and JS inline — no external dependencies.
        description: Short explanation of what this widget visualizes.
        height: Optional pixel height for the widget iframe (default 500).
    """
    widget = {
        "title": title,
        "html_content": html_content,
        "height": height,
    }
    presented_widgets = runtime.state.get("presented_widget", []) + [widget]
    msg = f"Widget '{title}' displayed successfully."
    return Command(
        update={
            "presented_widget": presented_widgets,
            "messages": [ToolMessage(msg, tool_call_id=runtime.tool_call_id)],
        }
    )