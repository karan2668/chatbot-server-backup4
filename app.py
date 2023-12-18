from fastapi import FastAPI, Body
from bs4 import BeautifulSoup
from urllib.request import urlopen
import io
from openai import OpenAI
from fastapi.responses import RedirectResponse

# app instance
app = FastAPI(title="Website Text Extraction API")

@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/docs", status_code=308)

@app.post("/api/website-extract")
def extract(data: dict = Body(...)):

    client = OpenAI(api_key=data["openAIAPIkey"])
    urls=data["websiteURLs"]

    urlsText=[]
    
    # Download content for each URL and combine with website content
    for url in urls:
        html = urlopen(url).read()
        soup = BeautifulSoup(html, features="html.parser")

        # kill all script and style elements
        for script in soup(["script", "style"]):
            script.extract()    # rip it out  
        
        # get text
        text = soup.get_text()

        # break into lines and remove leading and trailing space on each
        lines = (line.strip() for line in text.splitlines())
        # break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # drop blank lines
        text = '\n'.join(chunk for chunk in chunks if chunk)

        if text not in urlsText:
            urlsText.append(text)

    print(urlsText)
            
    fileIDs=[]
    for urlText in urlsText:
        file = client.files.create(
            file=io.BytesIO(urlText.encode()),
            purpose="assistants"
        )
        fileIDs.append(file.id)

    print(fileIDs)
    print(len(fileIDs))

    return fileIDs