# prompt: generate me a code of fetch post request

# import requests

# url = "http://127.0.0.1:8000/api/get-bot-message"

# data = {
#     "messagesId" : "65b8f1617fcbff3179d62b34",
#     "messages" : [],
#     "chatbotId" : "65b0cb6cbb7183ee1abd1e4b",
#     "query" : "what is Tweet Finder?"
# }

# response = requests.post(url, json=data)

# if response.status_code == 200:
#   print(response.json())
# else:
#   print("Error creating post:", response.status_code)

# import requests

# url = "http://127.0.0.1:8000/api/fetch-chatbot"

# data = {
#     "token" : "65b0cb6cbb7183ee1abd1e4b",
#     "messagesId" : "65b8b8d375196536d3dd8c18"
# }

# response = requests.post(url, json=data)

# if response.status_code == 200:
#   print(response.json())
# else:
#   print("Error creating post:", response.status_code)

import requests

url = "http://127.0.0.1:8000/api/get-bot-message"
data={"messagesId": "65b630cb6831727ea6bff363", "messages": [], "chatbotId": "65b0cb6cbb7183ee1abd1e4b", "query": "What is Tweet Finder?"}
with requests.post(url,json=data, stream=True) as r:
    for chunk in r.iter_content(1024):  # or, for line in r.iter_lines():
        print(chunk)