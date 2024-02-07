from dotenv import load_dotenv
import uvicorn

load_dotenv()

HOST = '127.0.0.1'

if __name__ == '__main__':
    uvicorn.run('app:app', host = HOST, reload = True)