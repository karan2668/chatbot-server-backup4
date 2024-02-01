from fastapi import FastAPI, Body
from openai import OpenAI
from fastapi.responses import RedirectResponse, StreamingResponse
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.request import urlopen
import requests
import asyncio
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId
from pinecone import Pinecone
# load config from .env file
load_dotenv()
MONGODB_URI = os.environ["MONGODB_URI"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
PINECONE_ENVIRONMENT = os.environ["PINECONE_ENVIRONMENT"]
PINECONE_INDEX = os.environ["PINECONE_INDEX"]

pc = Pinecone(api_key=PINECONE_API_KEY, environment=PINECONE_ENVIRONMENT)
pinecone_index = pc.Index(PINECONE_INDEX)

openCl = OpenAI(api_key=OPENAI_API_KEY)
client = MongoClient(MONGODB_URI)
mydb = client.pdfbot
chatbot_collection = mydb.Chatbot
profile_collection = mydb.Profile
messages_collection = mydb.Messages
message_collection = mydb.Message
faq_collection = mydb.FAQ
source_collection = mydb.Source

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
        else :
            profileId = chatbot_result["profileId"]

            # Get the current date and time in UTC
            current_date = datetime.now()

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
            top_k=5,
            vector=embeddings,
            include_metadata=True,
            namespace=file_key
        )
        # print("query_result",query_result)
        return query_result["matches"] or []
    except Exception as error:
        print("error querying embeddings", error)
        raise error


async def get_embeddings(text):
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
    
async def get_context(query, file_key):
    # print("query",query)
    # print("file_key",file_key)
    query_embeddings = await get_embeddings(query)
    
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

        # Get the current date and time in UTC
        current_date = datetime.now()

        chatbot_result = chatbot_collection.find_one({"_id": ObjectId(chatbotId)})

        faq_query = {"question": query}

        faq = faq_collection.find_one(faq_query)

        sources = source_collection.find({"chatbotId": ObjectId(chatbotId)})

        sources_list = list(sources)
        if sources is not None and len(sources_list) == 0:
            return {"content": chatbot_result["files_not_uploaded_message"], "role": "assistant"}

        if chatbot_result["messages_used"] == chatbot_result["messages_limit_per_day"]:
            return {"content": chatbot_result["messages_limit_warning_message"], "role": "assistant"}
        
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
            return {"content": faq["answer"], "role": "assistant"}

        context = ""

        for source in sources_list: 
            context += await get_context(query, source["file_key"])
        
        # print("context", context)
        
        support_details = "If you are facing any issue then mail your issue @pilare9421@vasteron.com"
        additional_guidelines = chatbot_result["bot_guidelines"]
        brandvoice_placeholder = f"START CONTEXT BLOCK\n{str(context)}\nEND OF CONTEXT BLOCK"

        response_length = "0 to 30 words only" if chatbot_result["response_length"] == "short" else None

        support_bot_prompt = f"""
            You are {chatbot_result["bot_name"]}, an AI assistant conversant ONLY in English, enthusiastic about representing and providing information about the company (if given) {chatbot_result["company_name"]} and its services you're designed to assist with.
            Given the following extracted chunks from a long document, your task is to create a final, engaging answer in English. If an answer can't be found in the chunks, politely say that you don't know and offer to assist with anything else.
            If you don't find an answer from the chunks, politely say that you don't know and ask if you can help with anything else. Don't try to make up an answer{brandvoice_placeholder}. Answer the user's query with more confidence.
            Ensure not to reference competitors while delivering responses.
            {support_details}
            Your goals are to:
            Answer the user's query in between {response_length}.
            - Show empathy towards user concerns, particularly related to the services you represent, referring to the company in first-person terms, such as 'we' or 'us'.
            - Confirm resolution, express gratitude to the user, and close the conversation with a polite, positive sign-off when no more assistance is needed.
            - Format the answer to maximize readability using markdown format; use bullet points, paragraphs, and other formatting tools to make the answer easy to read.
            - Answer ONLY in English irrespective of user's conversation or language used in the chunk.
            Do NOT answer in any other language other than English.
            {additional_guidelines}
            Here's an example:
            ===
            CONTEXT INFORMATION:
            CHUNK [1]: Our company offers a subscription-based music streaming service called 'MusicStreamPro.' We have two plans: Basic and Premium. The Basic plan costs $4.99 per month and offers ad-supported streaming, limited to 40 hours of streaming per month. The Premium plan costs $9.99 per month and offers ad-free streaming, unlimited streaming hours, and the ability to download songs for offline listening.
            CHUNK [2]: Not a relevant piece of information
            ---
            Question: What is the cost of the Premium plan, and what features does it include?
            Helpful Answer:
            The cost of the Premium plan is $9.99 per month. The features included in this plan are:
            - Ad-free streaming
            - Unlimited streaming hours
            - Ability to download songs for offline listening
            Please let me know if there's anything else I can assist you with!
            """

        prompt = {
            "role": "system",
            "content": support_bot_prompt
        }
        
        def stream():
            completion = openCl.chat.completions.create(
                model="gpt-3.5-turbo",
                stream=True,
                messages=[prompt, *filter(lambda m: m["role"] == "user", messages)]
            )
            for line in completion:
                chunk = line.choices[0].delta.content
                if chunk:
                    yield chunk

        # data = [
        #     {
        #         "role": "user",
        #         "content": query,
        #         "chatbotId": ObjectId(chatbotId),
        #         "messagesId": ObjectId(messagesId),
        #         "createdAt": current_date
        #     },
        #     {
        #         "role": "assistant",
        #         "content": response.choices[0].message.content,
        #         "chatbotId": ObjectId(chatbotId),
        #         "messagesId": ObjectId(messagesId),
        #         "createdAt": current_date
        #     }
        # ]

        # create_response = message_collection.insert_many(data)

        # print(create_response)

        # chatbot_collection.find_one_and_update({"_id": ObjectId(chatbotId)}, {"$inc": {"messages_used": 1}})

        # Use the generator in StreamingResponse
        return StreamingResponse(stream(), media_type='text/event-stream')
    

    except Exception as e:
        error = {"message": "Something went wrong", "statusCode": 500}
        print(e)
        return error