from fastapi import FastAPI, Body
from openai import OpenAI
from fastapi.responses import RedirectResponse
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.request import urlopen
import io, requests
import asyncio
import base64
from fastapi.middleware.cors import CORSMiddleware
import time
import os
import json

from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId
# load config from .env file
load_dotenv()
MONGODB_URI = os.environ["MONGODB_URI"]

client = MongoClient(MONGODB_URI)
mydb = client.pdfbot
chatbot_collection = mydb.Chatbot
profile_collection = mydb.Profile

# app instance
app = FastAPI(title="Website Text Extraction API")

# Set up CORS middleware
app.add_middleware(
    CORSMiddleware,
    # allow_origins=["http://127.0.0.1:5500", "https://lambent-halva-70f556.netlify.app", "https://chatbot-test-production.up.railway.app"],
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse("/docs", status_code=308)

@app.post("/api/website-extract")
def extract(data: dict = Body(...)):
    try:
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
    except Exception as e:
        return {"message" : "Unable to Extract Data" , "statusCode": 500}
    
# first function for scraping links
def scrape_sitemap(url):
  try:
      # Send a GET request to the sitemap URL
      response = requests.get(f"{url}/sitemap.xml")

      # Check if the request was successful (status code 200)
      if response.status_code == 200:
          # Parse the XML content
          tree = ET.fromstring(response.content)

          # Extract URLs from the XML tree
          urls = [element.text for element in tree.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]

          return urls
      else:
          # Print an error message if the request was not successful
          print(f"Failed to fetch sitemap from {url}. Status code: {response.status_code}")
          return [url]
  except Exception as e:
      # Print an error message if the request was not successful
      print(f"Failed to fetch sitemap from {url}. Status code: {response.status_code}")
      return [url]


# second function for scraping links
def extracted_sublinks(website_url):
  try:
    urls=[]
    response = requests.get(website_url)

    if response.status_code == 200:
        s= BeautifulSoup(response.text, "html.parser")
        for i in s.find_all("a"):
            href = i.attrs['href']
            if href.startswith("/"):
                site = website_url + href
                if site not in urls:
                    urls.append(site)
        return urls
    else:
        # Print an error message if the request was not successful
        print(f"Failed to fetch sitemap from {website_url}. Status code: {response.status_code}")
        return [website_url]
          
  except Exception as e:
    # Print an error message if the request was not successful
    print(f"Failed to fetch sitemap from {website_url}. Status code: {response.status_code}")
    return [website_url]


@app.post("/api/fetch-sublinks")
def extract(data: dict = Body(...)):
    try:
        URL=data["URL"]
        first_function = scrape_sitemap(URL)
        second_function = extracted_sublinks(URL)

        together = first_function + second_function

        return together
    except Exception as e:
        print({"message" : "Unable to Fetch Links" , "statusCode": 500})
        return []


@app.post("/api/fetch-user")
def fetch_user(data: dict = Body(...)):
    try:
        _id = data.get("token")  # Use get to avoid KeyError if 'bot_id' is not present

        # Get the profileId from the chatbot result
        chatbot_result = chatbot_collection.find_one({"_id": ObjectId(_id)})

        if chatbot_result is None:
            # Handle the case where chatbot_result is None (bot_id not found)
            error = {"message": "Bot not found", "statusCode": 404}
            return error

        # Query the profile collection using the profileId as user_id
        profile_id = str(chatbot_result.get("profileId"))
        user_query = {"_id": ObjectId(profile_id)}  # Use ObjectId to match the ID type

        user_result = profile_collection.find_one(user_query)

        if user_result is None:
            # Handle the case where user_result is None (profileId not found)
            error = {"message": "User not found", "statusCode": 404}
            return error

        # Remove the "profileId" property from chatbot_result
        del chatbot_result["profileId"]

        # Add the user profile to the chatbot_result
        chatbot_result["profile"] = user_result

        print("Chatbot object:", chatbot_result)
        print("profileId:", profile_id)

        # Assuming you need to close the MongoDB client (check if this is necessary in your case)
        # client.close()

        # Convert the result to JSON
        payload = json.loads(json.dumps(chatbot_result, default=str))
        return payload

    except Exception as e:
        error = {"message": "Internal Server Error", "statusCode": 500}
        print(e)
        return error
    
@app.post("/api/create-thread")
async def create_thread(data: dict = Body(...)):
    try:
        user_key=data["user_key"]
        # Decode a Base64 encoded string
        decoded_string = base64.b64decode(user_key)
        # Remove the b prefix using the decode() method
        decoded_string = decoded_string.decode('utf-8')

        # Remove the b prefix using the str.strip() method
        decoded_string = decoded_string.strip('b')

        # Print the decoded string
        print(decoded_string)

        client = OpenAI(api_key=decoded_string)
        
        thread = client.beta.threads.create()
        return thread.id
    except Exception as e:
        error = {"message" : "Unable to Fetch ChatbotUI" , "statusCode": 500}
        print(error)
        return error
    
@app.post("/api/create-user-message")
async def create_user_message(data: dict = Body(...)):
    try:
        user_key=data["user_key"]
        thread_id=data["thread_id"]
        query=data["query"]
        # Decode a Base64 encoded string
        decoded_string = base64.b64decode(user_key)
        # Remove the b prefix using the decode() method
        decoded_string = decoded_string.decode('utf-8')
        # Remove the b prefix using the str.strip() method
        decoded_string = decoded_string.strip('b')

        # Print the decoded string
        print(decoded_string)

        client = OpenAI(api_key=decoded_string)

        message = client.beta.threads.messages.create(
            thread_id,
            role = "user",
            content = query
        )
        # print(message)
        return message.content[0].text.value
    except Exception as e:
        error = {"message" : "Unable to Fetch ChatbotUI" , "statusCode": 500}
        print(error)
        return error
    
@app.post("/api/get-bot-message")
async def get_bot_message(data: dict = Body(...)):
    try:
        user_key=data["user_key"]
        thread_id = data["thread_id"]
        assistant_id = data["assistant_id"]

        # Decode a Base64 encoded string
        decoded_string = base64.b64decode(user_key)
        # Remove the b prefix using the decode() method
        decoded_string = decoded_string.decode('utf-8')

        # Remove the b prefix using the str.strip() method
        decoded_string = decoded_string.strip('b')

        # Print the decoded string
        print(decoded_string)

        client = OpenAI(api_key=decoded_string)

        print(thread_id)
        print(assistant_id)
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id
        )
        print(run.id)

        runStatus = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run.id  # Access 'id' directly without []
        )

        while runStatus.status != "completed":
            time.sleep(5)
            runStatus = client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id  # Access 'id' directly without []
            )
            print(runStatus)

            if runStatus.status == "failed":
                return runStatus

        messages = client.beta.threads.messages.list(thread_id)
        print("messagesssss", messages)
        
        return {"message":messages.data[0].content[0].text.value, "role" : messages.data[0].role}
    except Exception as e:
        error = {"message": "Unable to Fetch ChatbotUI", "statusCode": 500}
        print(e)
        return error