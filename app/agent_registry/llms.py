import os
from langchain_openai import AzureChatOpenAI
from dotenv import load_dotenv

load_dotenv()


llm = AzureChatOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    model=os.getenv("AZURE_OPENAI_MODEL"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_API_ENDPOINT"),
    temperature=0.0,
)

print(llm.invoke("Hello, how are you?"))