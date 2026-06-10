# sub-agent configurations
visual_designer_sub_agent = {
    "name": "visual-designer-agent",
    "description": "Delegate visual design to the sub-agent visual designer. Only give this designer one visual design at a time.",
    "system_prompt": "You are a helpful visual designer. You are given the need in text form and you need to design the HTML file to the best of your ability. You are also given a list of tools to help you design the visual design.",
    "tools": ["bash_tool", "str_replace", "present_files", "think_tool"],
}