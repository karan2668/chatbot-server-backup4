from fastapi import FastAPI, Body
from openai import OpenAI
from fastapi.responses import RedirectResponse, StreamingResponse
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import requests
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId
from pinecone import Pinecone
import base64

# load config from .env file
load_dotenv()
MONGODB_URI = os.environ["MONGODB_URI"]

# OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
PINECONE_ENVIRONMENT = os.environ["PINECONE_ENVIRONMENT"]
PINECONE_INDEX = os.environ["PINECONE_INDEX"]

pc = Pinecone(api_key=PINECONE_API_KEY, environment=PINECONE_ENVIRONMENT)
pinecone_index = pc.Index(PINECONE_INDEX)

# openCl = OpenAI(api_key=OPENAI_API_KEY)

client = MongoClient(MONGODB_URI)

mydb = client.pdfbot
chatbot_collection = mydb.Chatbot
profile_collection = mydb.Profile
messages_collection = mydb.Messages
message_collection = mydb.Message
faq_collection = mydb.FAQ
source_collection = mydb.Source

# Get the current date and time in UTC
current_date = datetime.utcnow()

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
def fetch_sublinks(data: dict = Body(...)):
    try:
        URL=data["URL"]
        first_function = scrape_sitemap(URL)
        second_function = extracted_sublinks(URL)

        together = first_function + second_function

        return together
    except Exception as e:
        print({"message" : "Unable to Fetch Links" , "statusCode": 500})
        return []


@app.post("/api/fetch-chatbot")
def fetch_user(data: dict = Body(...)):
    try:
        chatbotId = data.get("token")  
        messagesId = data.get("messagesId")  

        chatbot_result = chatbot_collection.find_one({"_id": ObjectId(chatbotId)})

        if chatbot_result is None:
            # Handle the case where chatbot_result is None (bot_id not found)
            error = {"message": "Bot not found", "statusCode": 404}
            return error
        
        chatbot_result["faqs"] = []
        
        
        if  messagesId is not None:
            chatbot_result["messagesId"] = messagesId
            
            chatbot_result["messages"] = []
            messages_query = {"messagesId": ObjectId(messagesId)}

            messages = message_collection.find(messages_query)

            for message in messages:
                chatbot_result["messages"].append(message)
        
        else :
            profileId = chatbot_result["profileId"]

            data = {
                "chatbotId": ObjectId(chatbotId),
                "profileId": ObjectId(profileId),
                "createdAt": current_date
            }

            session_created = messages_collection.insert_one(data)
            print(session_created.inserted_id)    
            chatbot_result["messagesId"] = session_created.inserted_id

        faqs_query = {"chatbotId": ObjectId(chatbotId)}

        faqs = faq_collection.find(faqs_query)

        for faq in faqs:
            chatbot_result["faqs"].append(faq)
            
        # Assuming you need to close the MongoDB client (check if this is necessary in your case)
        # client.close()

        # Convert the result to JSON
        payload = json.loads(json.dumps(chatbot_result, default=str))
        return payload

    except Exception as e:
        error = {"message": "Internal Server Error", "statusCode": 500}
        print(e)
        return error

def get_matches_from_embeddings(embeddings, file_key):
    try:
        # print("embeddings",embeddings)
        # print("file_key",file_key)
        query_result = pinecone_index.query(
            top_k=3,
            vector=embeddings,
            include_metadata=True,
            namespace=file_key
        )
        # print("query_result",query_result)
        return query_result["matches"] or []
    except Exception as error:
        print("error querying embeddings", error)
        raise error


async def get_embeddings(text, openCl):
    try:
        response = openCl.embeddings.create(
            model="text-embedding-ada-002",
            input=[text.replace("\n", " ")]
        )
        # print("get_embeddings", response.data[0].embedding)
        result = response.data[0].embedding
        return result
    except Exception as error:
        print("error calling openai embeddings api", error)
        raise error
    
async def get_context(query, file_key, openCl):
    # print("query",query)
    # print("file_key",file_key)
    query_embeddings = await get_embeddings(query, openCl)
    
    matches = get_matches_from_embeddings(query_embeddings, file_key)
    # print("matches", matches)

    qualifying_docs = [match for match in matches if match.get('score') and match['score'] > 0.7]

    # print("qualifying_docs", qualifying_docs)
    
    class Metadata:
        def __init__(self, text, page_number):
            self.text = text
            self.page_number = page_number

    docs = [match['metadata']['text'] for match in qualifying_docs if 'metadata' in match]
    # 5 vectors
    return "\n".join(docs)[:3000]

@app.post("/api/get-bot-message")
async def get_bot_message(data: dict = Body(...)):
    try:
        messagesId = data.get("messagesId")  
        messages = list(data.get("messages"))
        chatbotId = data.get("chatbotId")
        query = data.get("query")

        chatbot_result = chatbot_collection.find_one({"_id": ObjectId(chatbotId)})

        profile = profile_collection.find_one({"_id": ObjectId(chatbot_result["profileId"])})
        
        # Decode a Base64 encoded string
        # print(profile["user_key"])
        decoded_string = base64.b64decode(profile["user_key"])
        # Remove the b prefix using the decode() method
        decoded_string = decoded_string.decode('utf-8')

        # # Remove the b prefix using the str.strip() method
        decoded_string = decoded_string.strip('b')

        # # Print the decoded string
        # print(decoded_string)

        openCl = OpenAI(api_key=decoded_string)

        # print("profile", profile)

        faq_query = {"question": query}

        faq = faq_collection.find_one(faq_query)

        sources = source_collection.find({"chatbotId": ObjectId(chatbotId)})
        def error_message(text):
            yield text

        sources_list = list(sources)
        if sources is not None and len(sources_list) == 0:
            return StreamingResponse(error_message(str(chatbot_result["files_not_uploaded_message"])), media_type='text/event-stream')

        if chatbot_result["messages_used"] == chatbot_result["messages_limit_per_day"]:
            return StreamingResponse(error_message(str(chatbot_result["messages_limit_warning_message"])), media_type='text/event-stream')
        
        if faq is not None and faq["question"] == query:
            data = [
                {
                    "role": "user",
                    "content": query,
                    "chatbotId": ObjectId(chatbotId),
                    "messagesId": ObjectId(messagesId),
                    "createdAt": current_date
                },
                {
                    "role": "assistant",
                    "content": faq["answer"],
                    "chatbotId": ObjectId(chatbotId),
                    "messagesId": ObjectId(messagesId),
                    "createdAt": current_date
                }
            ]
            message_collection.insert_many(data)
            chatbot_collection.find_one_and_update({"_id": ObjectId(chatbotId)}, {"$inc": {"messages_used": 1}})
            return StreamingResponse(error_message(str(faq["answer"])), media_type='text/event-stream')

        uniqueContexts = set()

        for source in sources_list: 
            uniqueContexts.add(await get_context(query, source["file_key"], openCl))
        
        context = ''.join(uniqueContexts)
        print("context", context)

        response_length = (
            "1 or 2"  # First condition
            if chatbot_result["response_length"] == "short"
            else "2 or 3"  # Second condition
            if chatbot_result["response_length"] == "medium"
            else "3 or 4"  # Third condition
        )


        support_bot_prompt = f"""
            As {chatbot_result["bot_name"]}, you clarify {chatbot_result["company_name"]}'s information and services, condensing extensive documents into clear responses. If uncertain, admit it and offer further help. Guidelines:
            - Don't respond in more than {response_length} sentences.
            - Refer to the company as 'we' or 'us'.
            - Confirm issue resolution, thank users, and end politely.
            - Use bullet points and paragraphs for readability.
            - {chatbot_result["bot_guidelines"]}.
            
            Example:
            Sections:
            
            1. 'MusicStreamPro' provides Basic ($4.99/mo, 40 hours ad-supported streaming) and Premium plans ($9.99/mo, ad-free/unlimited streaming, song downloads).
            2. Irrelevant info.
            
            Question: Premium plan details?
            Answer:
            Premium is $9.99/mo, offering:
            
            - No ads
            - Unlimited streaming
            - Song downloads
            Need more help? Just ask!
            
            START CONTEXT BLOCK\n
            {str(context)}\n
            END OF CONTEXT BLOCK
            """

        prompt = {
            "role": "system",
            "content": support_bot_prompt
        }
        
        def stream():
            completion = openCl.chat.completions.create(
                model="gpt-4-turbo-preview" if chatbot_result["is_gpt_4"] else "gpt-3.5-turbo",
                stream=True,
                messages=[prompt, *filter(lambda m: m["role"] == "user", messages)]
            )

            full_stream_text = ""
            for line in completion:
                chunk = line.choices[0].delta.content
                if chunk is not None:  # Check if chunk is not None
                    full_stream_text += chunk

                # Other processing
                finish_reason = line.choices[0].finish_reason
                if finish_reason == "stop":
                    # This is the end of the stream
                    # Save messages to the database
                    data = [
                        {
                            "role": "user",
                            "content": query,
                            "chatbotId": ObjectId(chatbotId),
                            "messagesId": ObjectId(messagesId),
                            "createdAt": current_date
                        },
                        {
                            "role": "assistant",
                            "content": full_stream_text,
                            "chatbotId": ObjectId(chatbotId),
                            "messagesId": ObjectId(messagesId),
                            "createdAt": current_date
                        }
                    ]

                    create_response = message_collection.insert_many(data)

                    print(create_response)

                    chatbot_collection.find_one_and_update({"_id": ObjectId(chatbotId)}, {"$inc": {"messages_used": 1}})
                    break  # Exit the loop
                if chunk:
                    yield chunk

        # 

        # Use the generator in StreamingResponse
        return StreamingResponse(stream(), media_type='text/event-stream')
    

    except Exception as e:
        error = {"message": "Something went wrong", "statusCode": 500}
        print(e)
        return error
    
