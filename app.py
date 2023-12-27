from fastapi import FastAPI, Body, HTTPException
from openai import OpenAI
from fastapi.responses import RedirectResponse
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.request import urlopen
import io, requests

# app instance
app = FastAPI(title="Website Text Extraction API")

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
        
