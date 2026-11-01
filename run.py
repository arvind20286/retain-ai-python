import uvicorn
from retain_ai.config import settings

if __name__ == "__main__":
    uvicorn.run("retain_ai.main:app", host=settings.host, port=settings.port, reload=True)

