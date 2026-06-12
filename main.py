import os
import uvicorn
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

from app import app, logger

def main():
    HOST = os.getenv("APP_HOST")
    PORT = int(os.getenv("APP_PORT"))
    print(HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)

if __name__ == "__main__":
    main()