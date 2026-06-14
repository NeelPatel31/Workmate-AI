# sub-agent configurations
visual_designer_sub_agent = {
    "name": "visual-designer-agent",
    "description": "Delegate visual design to the sub-agent visual designer. Only give this designer one visual design at a time.",
    "system_prompt": "You are a helpful visual designer. You are given the need in text form and you need to design the HTML file to the best of your ability. You are also given a list of tools to help you design the visual design.",
    "tools": [
        "bash_tool",
        "view_file",
        "str_replace",
        "create_file",
        "insert",
        "present_files",
        "think_tool",
    ],
}

all_subagents = [visual_designer_sub_agent]


def get_subagents_xml() -> str:
    """Return all sub-agent configurations as a newline-joined XML string.

    Each block includes name, description, and available tools.
    """
    xml_blocks: list[str] = []

    for agent in all_subagents:
        name = agent.get("name", "")
        description = agent.get("description", "")
        tools = agent.get("tools", [])

        if not name or not description:
            continue

        tools_str = ", ".join(tools)

        xml_blocks.append(
            f"<subagent>\n"
            f"  <name>{name}</name>\n"
            f"  <description>{description}</description>\n"
        )
        if tools_str:
            xml_blocks.append(
            f"  <tools>{tools_str}</tools>\n"
        )
        xml_blocks.append(
            f"</subagent>\n"
        )

    return "\n".join(xml_blocks)


CURRENTLY_AVAILABLE_SUBAGENTS = get_subagents_xml()

