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
from datetime import datetime, timezone

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
messages_collection = mydb.Messages
message_collection = mydb.Message
faq_collection = mydb.FAQ

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
        _id = data.get("token")  # Use get to avoid KeyError if '_id' is not present

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

        chatbot_result["faqs"] = []

        faqs_query = {"chatbotId": ObjectId(_id)}

        faqs = faq_collection.find(faqs_query)

        for faq in faqs:
            chatbot_result["faqs"].append(faq)
        
        # Assuming you need to close the MongoDB client (check if this is necessary in your case)
        # client.close()
            
            # Decode a Base64 encoded string
        print(user_result["user_key"])
        decoded_string = base64.b64decode(user_result["user_key"])
        # Remove the b prefix using the decode() method
        decoded_string = decoded_string.decode('utf-8')

        # # Remove the b prefix using the str.strip() method
        decoded_string = decoded_string.strip('b')

        # # Print the decoded string
        print(decoded_string)

        client = OpenAI(api_key=decoded_string)
            
        assistant = client.beta.assistants.retrieve(chatbot_result["bot_id"])

        print("assistant", assistant)

        chatbot_result['length_file_ids'] = len(assistant.file_ids)

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
        chatbot_id=data["chatbot_id"]
        messages_id=data["messages_id"]
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

        # Get the current date and time in UTC
        current_date = datetime.now()
        
        data= {
             "role": "USER",
             "content": message.content[0].text.value,
             "chatbotId": ObjectId(chatbot_id),
             "messagesId": ObjectId(messages_id),
             "createdAt": current_date
        }

        user_message = message_collection.insert_one(data)
        print(user_message)

        return message.content[0].text.value
    except Exception as e:
        error = {"message" : "Unable to Fetch ChatbotUI" , "statusCode": 500}
        print(error)
        return error
    
@app.post("/api/save-session")
async def save_session(data: dict = Body(...)):
    try:
        thread_id=data["thread_id"]
        chatbot_id=data["chatbot_id"]
        profile_id=data["profile_id"]

        # Get the current date and time in UTC
        current_date = datetime.now()

        data = {
            "thread_id": thread_id,
            "chatbotId": ObjectId(chatbot_id),
            "profileId": ObjectId(profile_id),
            "createdAt": current_date 
        }

        messages = messages_collection.insert_one(data)
        print(messages.inserted_id)
        # Convert the result to JSON
        payload = json.loads(json.dumps(messages.inserted_id, default=str))
        return payload
    except Exception as e:
        error = {"message" : "Unable to Fetch ChatbotUI" , "statusCode": 500}
        print(error)
        return error
    
@app.post("/api/get-bot-message")
async def get_bot_message(data: dict = Body(...)):
    try:
        user_key = data["user_key"]
        thread_id = data["thread_id"]
        assistant_id = data["assistant_id"]
        chatbot_id = data["chatbot_id"]
        query = data["query"]
        length_file_ids = data["length_file_ids"]
        profile_id = data["profile_id"]
        count = data["count"]
        # Get the current date and time in UTC
        current_date = datetime.now()

        # Decode a Base64 encoded string
        decoded_string = base64.b64decode(user_key).decode('utf-8').strip('b')
        print(decoded_string)

        client = OpenAI(api_key=decoded_string)

        chatbot_result = chatbot_collection.find_one({"bot_id": assistant_id})
        print(chatbot_result)

        if int(length_file_ids) == 0:
            return {"message": chatbot_result["files_not_uploaded_message"], "role": "BOT"}

        if chatbot_result["messages_used"] == chatbot_result["messages_limit_per_day"]:
            return {"message": chatbot_result["messages_limit_warning_message"], "role": "BOT"}

        if (int(count) == 0):
            data = {
                "thread_id": thread_id,
                "chatbotId": ObjectId(chatbot_id),
                "profileId": ObjectId(profile_id),
                "createdAt": current_date 
            }   
            messages = messages_collection.insert_one(data)
            print(messages.inserted_id)

        get_created_messages = messages_collection.find_one({"thread_id": thread_id})

        print("get_created_messagesssasa", get_created_messages)

        messages_id = str(get_created_messages["_id"])

        print("messages_iddddd", messages_id)
        
        message = client.beta.threads.messages.create(
            thread_id,
            role="user",
            content=query
        )

        data = {
            "role": "USER",
            "content": message.content[0].text.value,
            "chatbotId": ObjectId(chatbot_id),
            "messagesId": ObjectId(messages_id),
            "createdAt": current_date
        }

        user_message = message_collection.insert_one(data)
        print(user_message)

        faqs_query = {"chatbotId": ObjectId(chatbot_id)}
        faqs = faq_collection.find(faqs_query)

        findFaq = next((faq for faq in faqs if query in faq['question']), None)

        if findFaq and "answer" in findFaq:
            data = {
                "role": "BOT",
                "content": findFaq["answer"],
                "chatbotId": ObjectId(chatbot_id),
                "messagesId": ObjectId(messages_id),
                "createdAt": current_date
            }
            message_collection.insert_one(data)
            chatbot_collection.find_one_and_update({"bot_id": assistant_id}, {"$inc": {"messages_used": 1}})
            return {"message": str(findFaq["answer"]), "role": "BOT"}

        print(thread_id)
        print(assistant_id)

        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id
        )
        print(run.id)

        run_status = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run.id
        )

        while run_status.status != "completed":
            time.sleep(1)
            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            print(run_status)

            if run_status.status == "failed":
                return run_status

        messages = client.beta.threads.messages.list(thread_id)

        print("messages", messages.data[0].content[0].text.value)

        data = {
            "role": "BOT",
            "content": messages.data[0].content[0].text.value,
            "chatbotId": ObjectId(chatbot_id),
            "messagesId": ObjectId(messages_id),
            "createdAt": current_date
        }

        bot_message = message_collection.insert_one(data)
        print(bot_message)

        chatbot_collection.find_one_and_update({"bot_id": assistant_id}, {"$inc": {"messages_used": 1}})

        return {"message": messages.data[0].content[0].text.value, "role": "BOT"}
    except Exception as e:
        error = {"message": "Something went wrong", "statusCode": 500}
        print(e)
        return error