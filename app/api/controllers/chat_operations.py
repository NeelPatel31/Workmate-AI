from ...agent import workmate_agent
from ...utils import logger

def build_agent_query(user_query: str, uploaded_files: list[dict]) -> str:
    main_query = ""
    if uploaded_files:
        main_query += "<uploaded_files>\n"
        for file in uploaded_files:
            main_query += f"<file>\n"
            main_query += f"  <name>{file['file_name']}</name>\n"
            main_query += f"  <path>{file['file_path']}</path>\n"
            main_query += f"</file>\n"
        main_query += "</uploaded_files>\n"
    main_query += f"<user_query>\n{user_query}\n</user_query>\n"
    return main_query.strip()

def chat(session_id: str, user_query: str, uploaded_files: list[dict]) -> str:
    agent_query = build_agent_query(user_query, uploaded_files)
    response = workmate_agent.invoke({"messages": [{"role": "user", "content": agent_query}]})
    return response["messages"][-1].content