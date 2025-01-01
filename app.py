from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup
import requests
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

# Initialize FastAPI
app = FastAPI()

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "web_scraper"
COLLECTION_NAME = "templates"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

# Directory setup for saving static files
STATIC_DIR = "static"
CSS_DIR = os.path.join(STATIC_DIR, "css")
JS_DIR = os.path.join(STATIC_DIR, "js")

os.makedirs(CSS_DIR, exist_ok=True)
os.makedirs(JS_DIR, exist_ok=True)

# Mount static directory for serving CSS and JS
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Jinja2 Templates
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    Render the home page with the scrape form.
    """
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/scrape")
async def scrape_website(url: str = Form(...)):
    """
    Scrape a website and store the results.
    """
    # Validate URL
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch the URL: {e}")

    soup = BeautifulSoup(response.content, "html.parser")

    # Extract HTML
    html_content = soup.prettify()

    # Save external CSS files
    css_files = []
    for idx, link_tag in enumerate(soup.find_all("link", {"rel": "stylesheet"})):
        href = link_tag.get("href")
        if href:
            css_url = urljoin(url, href)
            try:
                css_response = requests.get(css_url)
                css_response.raise_for_status()
                css_filename = f"style_{idx}.css"
                css_path = os.path.join(CSS_DIR, css_filename)
                with open(css_path, "w", encoding="utf-8") as f:
                    f.write(css_response.text)
                css_files.append(f"/static/css/{css_filename}")
            except requests.exceptions.RequestException:
                continue  # Skip if the CSS file can't be fetched

    # Save external JS files
    js_files = []
    for idx, script_tag in enumerate(soup.find_all("script", {"src": True})):
        src = script_tag.get("src")
        if src:
            js_url = urljoin(url, src)
            try:
                js_response = requests.get(js_url)
                js_response.raise_for_status()
                js_filename = f"script_{idx}.js"
                js_path = os.path.join(JS_DIR, js_filename)
                with open(js_path, "w", encoding="utf-8") as f:
                    f.write(js_response.text)
                js_files.append(f"/static/js/{js_filename}")
            except requests.exceptions.RequestException:
                continue  # Skip if the JS file can't be fetched

    # Check if the URL is already in the database
    if collection.find_one({"url": url}):
        raise HTTPException(status_code=400, detail="This URL has already been scraped.")

    # Store in MongoDB
    document = {
        "url": url,
        "html": html_content,
        "css_files": css_files,
        "js_files": js_files
    }
    result = collection.insert_one(document)

    return RedirectResponse(url=f"/render/{result.inserted_id}", status_code=303)


@app.get("/render", response_class=RedirectResponse)
async def render_template(request: Request, template_id: str):
    """
    Render the template from the database using the provided ID.
    """
    try:
        # Fetch the template by ID
        document = collection.find_one({"_id": ObjectId(template_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid template ID.")

    if not document:
        raise HTTPException(status_code=404, detail="Template not found.")

    html_content = document["html"]
    css_files = document["css_files"]
    js_files = document["js_files"]

    return templates.TemplateResponse(
        "render.html",
        {
            "request": request,
            "html_content": html_content,
            "css_files": css_files,
            "js_files": js_files,
        },
    )
