from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import requests
import json
from geopy.distance import geodesic
import math
import psycopg
from datetime import datetime, time
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re
from playwright.async_api import async_playwright
from fake_useragent import UserAgent
import os
from dotenv import load_dotenv
from crawl4ai import AsyncWebCrawler
from crawl4ai.extraction_strategy import LLMExtractionStrategy
import openai

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MAX_LISTINGS_PER_SITE = int(os.getenv("MAX_LISTINGS_PER_SITE", "20"))
SCRAPING_TIMEOUT = int(os.getenv("SCRAPING_TIMEOUT", "30"))

app = FastAPI(title="Kenya Housing Location Finder API")

# Disable CORS. Do not remove this for full-stack development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

class LocationSearchRequest(BaseModel):
    query: str
    country: str = "Kenya"

class CommuteRequest(BaseModel):
    work_lat: float
    work_lng: float
    max_commute_minutes: int
    transport_mode: str = "driving"
    work_start_time: Optional[str] = "08:00"
    work_end_time: Optional[str] = "17:00"

class LocationResult(BaseModel):
    display_name: str
    lat: float
    lng: float
    place_id: str

class IsochronePoint(BaseModel):
    lat: float
    lng: float

class NamedArea(BaseModel):
    name: str
    lat: float
    lng: float
    commute_time_minutes: int
    description: str

class HousingListingRequest(BaseModel):
    areas: List[str]
    min_budget: Optional[int] = None
    max_budget: Optional[int] = None
    property_type: Optional[str] = "any"  # apartment, house, studio, any
    bedrooms: Optional[int] = None
    api_key: Optional[str] = None

class HousingListing(BaseModel):
    title: str
    price: Optional[int]
    location: str
    area: str
    bedrooms: Optional[int]
    property_type: str
    description: str
    contact: Optional[str]
    url: str
    source: str
    images: List[str] = []

@app.get("/")
def read_root():
    return {"message": "Kenya Housing Location Finder API", "status": "running"}

@app.post("/search-locations", response_model=List[LocationResult])
async def search_locations(request: LocationSearchRequest):
    """Search for locations in Kenya using Nominatim API"""
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": f"{request.query}, {request.country}",
            "format": "json",
            "limit": 10,
            "countrycodes": "ke",  # Kenya country code
            "addressdetails": 1
        }
        
        headers = {
            "User-Agent": "KenyaHousingFinder/1.0"
        }
        
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        
        results = []
        for item in data:
            results.append(LocationResult(
                display_name=item.get("display_name", ""),
                lat=float(item.get("lat", 0)),
                lng=float(item.get("lon", 0)),
                place_id=str(item.get("place_id", ""))
            ))
        
        return results
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Location search failed: {str(e)}")

def get_traffic_multiplier(work_start_time: str, transport_mode: str) -> float:
    """Get traffic multiplier based on work start time and transport mode"""
    try:
        start_hour = int(work_start_time.split(':')[0])
        
        if transport_mode == "driving":
            if 7 <= start_hour <= 9 or 17 <= start_hour <= 19:
                return 0.4  # Heavy traffic, 40% of normal speed
            elif 6 <= start_hour <= 10 or 16 <= start_hour <= 20:
                return 0.6  # Moderate traffic, 60% of normal speed
            else:
                return 0.8  # Light traffic, 80% of normal speed
        elif transport_mode == "public_transport":
            if 7 <= start_hour <= 9 or 17 <= start_hour <= 19:
                return 0.5  # Heavy traffic affects matatus too
            else:
                return 0.7  # Less affected than cars
        else:
            return 1.0  # Walking/cycling not affected by traffic
    except:
        return 0.7  # Default moderate traffic

@app.post("/calculate-isochrone", response_model=List[IsochronePoint])
async def calculate_isochrone(request: CommuteRequest):
    """Calculate isochrone (reachable area) based on commute time with traffic consideration"""
    try:
        base_speeds = {
            "driving": 45,  # Optimistic speed without traffic
            "walking": 5,
            "cycling": 15,
            "public_transport": 25  # Matatu/bus optimistic speed
        }
        
        base_speed = base_speeds.get(request.transport_mode, 45)
        traffic_multiplier = get_traffic_multiplier(request.work_start_time, request.transport_mode)
        actual_speed = base_speed * traffic_multiplier
        
        max_distance_km = (actual_speed * request.max_commute_minutes) / 60
        
        center_lat = request.work_lat
        center_lng = request.work_lng
        
        points = []
        num_points = 32  # Number of points to create the circle
        
        for i in range(num_points):
            angle = (2 * math.pi * i) / num_points
            
            lat_offset = (max_distance_km / 111) * math.cos(angle)
            lng_offset = (max_distance_km / (111 * math.cos(math.radians(center_lat)))) * math.sin(angle)
            
            point_lat = center_lat + lat_offset
            point_lng = center_lng + lng_offset
            
            points.append(IsochronePoint(lat=point_lat, lng=point_lng))
        
        return points
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Isochrone calculation failed: {str(e)}")

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.post("/suggest-areas", response_model=List[NamedArea])
async def suggest_areas(request: CommuteRequest):
    """Suggest named residential areas within commute time"""
    try:
        nairobi_areas = [
            {"name": "Parklands", "lat": -1.2634, "lng": 36.8581, "description": "Upmarket residential area with good amenities"},
            {"name": "Ruaka", "lat": -1.2089, "lng": 36.8456, "description": "Growing suburb with modern housing"},
            {"name": "Highridge", "lat": -1.3167, "lng": 36.7833, "description": "Quiet residential area with good schools"},
            {"name": "Spring Valley", "lat": -1.2833, "lng": 36.7833, "description": "Leafy suburb popular with expats"},
            {"name": "Lavington", "lat": -1.2833, "lng": 36.7667, "description": "Upscale neighborhood with shopping centers"},
            {"name": "Kilimani", "lat": -1.2921, "lng": 36.7833, "description": "Central location with apartments and nightlife"},
            {"name": "Kileleshwa", "lat": -1.2833, "lng": 36.7833, "description": "Residential area close to the city center"},
            {"name": "Runda", "lat": -1.2167, "lng": 36.8167, "description": "Exclusive gated community"},
            {"name": "Muthaiga", "lat": -1.2500, "lng": 36.8333, "description": "Historic upmarket area"},
            {"name": "Westlands", "lat": -1.2667, "lng": 36.8000, "description": "Commercial and residential hub"},
            {"name": "Kasarani", "lat": -1.2167, "lng": 36.9000, "description": "Affordable housing with good transport links"},
            {"name": "Thika Road", "lat": -1.2000, "lng": 36.9000, "description": "Developing area with new housing projects"},
            {"name": "Karen", "lat": -1.3167, "lng": 36.7000, "description": "Leafy suburb with large plots"},
            {"name": "Langata", "lat": -1.3500, "lng": 36.7333, "description": "Residential area near national park"},
            {"name": "Embakasi", "lat": -1.3167, "lng": 36.8833, "description": "Growing residential area"},
        ]
        
        base_speeds = {
            "driving": 45,
            "walking": 5,
            "cycling": 15,
            "public_transport": 25
        }
        
        base_speed = base_speeds.get(request.transport_mode, 45)
        traffic_multiplier = get_traffic_multiplier(request.work_start_time, request.transport_mode)
        actual_speed = base_speed * traffic_multiplier
        
        suggested_areas = []
        
        for area in nairobi_areas:
            distance_km = geodesic(
                (request.work_lat, request.work_lng),
                (area["lat"], area["lng"])
            ).kilometers
            
            commute_time = (distance_km / actual_speed) * 60
            
            if commute_time <= request.max_commute_minutes:
                suggested_areas.append(NamedArea(
                    name=area["name"],
                    lat=area["lat"],
                    lng=area["lng"],
                    commute_time_minutes=int(commute_time),
                    description=area["description"]
                ))
        
        suggested_areas.sort(key=lambda x: x.commute_time_minutes)
        
        return suggested_areas
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Area suggestion failed: {str(e)}")

async def ai_scrape_housing_site(site_url: str, area: str, api_key: Optional[str] = None, websocket: WebSocket = None) -> List[HousingListing]:
    """AI-powered scraping using Crawl4AI with user-configurable API keys"""
    listings = []
    
    if websocket:
        await websocket.send_text(json.dumps({
            "type": "progress",
            "message": f"Starting AI-powered scraping for {area}...",
            "site": site_url,
            "progress": 10
        }))
    
    try:
        effective_api_key = api_key or OPENAI_API_KEY
        if not effective_api_key and not USE_LOCAL_LLM:
            if websocket:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "No AI API key provided. Please enter your OpenAI API key."
                }))
            return await scrape_buyrentkenya_fallback(area)
        
        if websocket:
            await websocket.send_text(json.dumps({
                "type": "progress", 
                "message": f"Initializing AI crawler for {area}...",
                "progress": 20
            }))
        
        extraction_strategy = LLMExtractionStrategy(
            provider="openai/gpt-4o-mini" if not USE_LOCAL_LLM else "ollama/llama3.2",
            api_token=effective_api_key if not USE_LOCAL_LLM else None,
            base_url=None if not USE_LOCAL_LLM else OLLAMA_BASE_URL,
            instruction=f"""
            Extract housing rental listings from this webpage for the area {area} in Kenya. 
            For each property listing found, extract the following information:
            
            - title: Property title or name
            - price: Monthly rental price in KSh (extract numbers only, convert to integer)
            - location: Specific location or neighborhood 
            - bedrooms: Number of bedrooms (extract number)
            - property_type: Type of property (apartment, house, studio, villa, etc.)
            - description: Brief property description
            - contact: Phone number or email if available
            - url: Link to the full listing
            
            Return the data as a JSON array of objects. Only include actual rental properties, ignore ads or non-rental content.
            Focus on properties in or near {area}.
            """,
            schema={
                "type": "object",
                "properties": {
                    "listings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "price": {"type": "string"},
                                "location": {"type": "string"},
                                "bedrooms": {"type": "string"},
                                "property_type": {"type": "string"},
                                "description": {"type": "string"},
                                "contact": {"type": "string"},
                                "url": {"type": "string"}
                            }
                        }
                    }
                }
            }
        )
        
        if websocket:
            await websocket.send_text(json.dumps({
                "type": "progress", 
                "message": f"AI analyzing webpage content for {area}...",
                "progress": 50
            }))
        
        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(
                url=site_url,
                extraction_strategy=extraction_strategy,
                bypass_cache=True,
                timeout=SCRAPING_TIMEOUT
            )
            
            if websocket:
                await websocket.send_text(json.dumps({
                    "type": "progress", 
                    "message": f"Processing AI extraction results for {area}...",
                    "progress": 80
                }))
            
            if result.extracted_content:
                try:
                    extracted_data = json.loads(result.extracted_content)
                    raw_listings = extracted_data.get('listings', [])
                    
                    for item in raw_listings[:MAX_LISTINGS_PER_SITE]:
                        if isinstance(item, dict):
                            listing = HousingListing(
                                title=item.get('title', 'No title'),
                                price=extract_price(str(item.get('price', 0))),
                                location=item.get('location', area),
                                area=area,
                                bedrooms=extract_bedrooms(str(item.get('bedrooms', ''))),
                                property_type=item.get('property_type', 'apartment').lower(),
                                description=item.get('description', 'No description')[:200],
                                contact=item.get('contact'),
                                url=item.get('url', ''),
                                source="AI-Powered Crawl4AI",
                                images=[]
                            )
                            listings.append(listing)
                            
                except json.JSONDecodeError:
                    if websocket:
                        await websocket.send_text(json.dumps({
                            "type": "progress",
                            "message": f"AI extraction failed, using fallback for {area}...",
                            "progress": 85
                        }))
                    listings = await scrape_with_traditional_method(site_url, area)
            
            if websocket:
                await websocket.send_text(json.dumps({
                    "type": "progress",
                    "message": f"AI found {len(listings)} listings in {area}",
                    "progress": 95
                }))
                
    except Exception as e:
        if websocket:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"AI scraping failed for {area}: {str(e)}, using fallback"
            }))
        listings = await scrape_buyrentkenya_fallback(area)
    
    return listings

async def scrape_with_traditional_method(site_url: str, area: str) -> List[HousingListing]:
    """Traditional scraping fallback when AI extraction fails"""
    listings = []
    
    try:
        ua = UserAgent()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=ua.random,
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            await page.goto(site_url, wait_until='networkidle', timeout=30000)
            content = await page.content()
            await browser.close()
            
            soup = BeautifulSoup(content, 'html.parser')
            
            if 'buyrentkenya' in site_url.lower():
                listings = await extract_buyrentkenya_listings(soup, area)
            elif 'pigiame' in site_url.lower() or 'jiji' in site_url.lower():
                listings = await extract_pigiame_listings(soup, area)
            else:
                listings = await extract_generic_listings(soup, area, site_url)
                
    except Exception as e:
        print(f"Traditional scraping also failed: {str(e)}")
    
    return listings

async def extract_buyrentkenya_listings(soup: BeautifulSoup, area: str) -> List[HousingListing]:
    """Extract listings from BuyRentKenya with enhanced selectors"""
    listings = []
    
    listing_selectors = [
        '.property-item', '.listing-item', '.property-card', 
        '.search-result-item', '.property-listing', '[data-property-id]'
    ]
    
    listing_elements = []
    for selector in listing_selectors:
        elements = soup.select(selector)
        if elements:
            listing_elements = elements
            break
    
    for element in listing_elements[:20]:  # Limit to 20 listings
        try:
            title_selectors = ['.property-title', '.listing-title', 'h3', 'h4', '.title']
            title = "No title"
            for sel in title_selectors:
                title_elem = element.select_one(sel)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    break
            
            price_selectors = ['.price', '.property-price', '.listing-price', '[class*="price"]']
            price_text = ""
            for sel in price_selectors:
                price_elem = element.select_one(sel)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    break
            
            location_selectors = ['.location', '.property-location', '.address', '[class*="location"]']
            location = area
            for sel in location_selectors:
                loc_elem = element.select_one(sel)
                if loc_elem:
                    location = loc_elem.get_text(strip=True)
                    break
            
            url = ""
            link_elem = element.select_one('a[href]')
            if link_elem:
                url = link_elem.get('href', '')
                if url.startswith('/'):
                    url = 'https://www.buyrentkenya.com' + url
            
            # Extract description
            desc_selectors = ['.description', '.property-description', '.summary', 'p']
            description = "No description"
            for sel in desc_selectors:
                desc_elem = element.select_one(sel)
                if desc_elem:
                    description = desc_elem.get_text(strip=True)[:200]
                    break
            
            listing = HousingListing(
                title=title,
                price=extract_price(price_text),
                location=location,
                area=area,
                bedrooms=extract_bedrooms(title + " " + description),
                property_type=extract_property_type(title + " " + description),
                description=description,
                contact=None,
                url=url,
                source="Enhanced Playwright Scraping",
                images=[]
            )
            listings.append(listing)
            
        except Exception as e:
            continue
    
    return listings

async def extract_pigiame_listings(soup: BeautifulSoup, area: str) -> List[HousingListing]:
    """Extract listings from PigiaMe/Jiji with enhanced selectors"""
    listings = []
    
    listing_selectors = [
        '.listing', '.ad-item', '.product-item', 
        '[data-ad-id]', '.search-item', '.classified-item'
    ]
    
    listing_elements = []
    for selector in listing_selectors:
        elements = soup.select(selector)
        if elements:
            listing_elements = elements
            break
    
    for element in listing_elements[:20]:
        try:
            title_selectors = ['.ad-title', '.listing-title', 'h3', 'h4', '.title', 'a[title]']
            title = "No title"
            for sel in title_selectors:
                title_elem = element.select_one(sel)
                if title_elem:
                    title = title_elem.get_text(strip=True) or title_elem.get('title', '')
                    break
            
            price_selectors = ['.price', '.ad-price', '.listing-price', '[class*="price"]']
            price_text = ""
            for sel in price_selectors:
                price_elem = element.select_one(sel)
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    break
            
            location_selectors = ['.location', '.ad-location', '.region', '[class*="location"]']
            location = area
            for sel in location_selectors:
                loc_elem = element.select_one(sel)
                if loc_elem:
                    location = loc_elem.get_text(strip=True)
                    break
            
            url = ""
            link_elem = element.select_one('a[href]')
            if link_elem:
                url = link_elem.get('href', '')
                if url.startswith('/'):
                    url = 'https://www.pigiame.co.ke' + url
            
            listing = HousingListing(
                title=title,
                price=extract_price(price_text),
                location=location,
                area=area,
                bedrooms=extract_bedrooms(title),
                property_type=extract_property_type(title),
                description=title,
                contact=None,
                url=url,
                source="Enhanced Playwright Scraping",
                images=[]
            )
            listings.append(listing)
            
        except Exception as e:
            continue
    
    return listings

async def extract_generic_listings(soup: BeautifulSoup, area: str, site_url: str) -> List[HousingListing]:
    """Generic extraction for unknown sites"""
    listings = []
    
    potential_listings = soup.find_all(['div', 'article', 'section'], 
                                     class_=re.compile(r'(listing|property|ad|item|card)', re.I))
    
    for element in potential_listings[:15]:
        try:
            title_elem = element.find(['h1', 'h2', 'h3', 'h4', 'h5'])
            title = title_elem.get_text(strip=True) if title_elem else "Property Listing"
            
            price_text = ""
            price_elem = element.find(text=re.compile(r'KSh|Ksh|ksh|\d+,?\d*'))
            if price_elem:
                price_text = str(price_elem).strip()
            
            listing = HousingListing(
                title=title,
                price=extract_price(price_text),
                location=area,
                area=area,
                bedrooms=extract_bedrooms(title),
                property_type=extract_property_type(title),
                description=title,
                contact=None,
                url=site_url,
                source="Generic Enhanced Scraping",
                images=[]
            )
            listings.append(listing)
            
        except Exception as e:
            continue
    
    return listings

async def scrape_buyrentkenya_fallback(area: str) -> List[HousingListing]:
    """Fallback scraping using BeautifulSoup"""
    listings = []
    try:
        search_url = f"https://www.buyrentkenya.com/houses-for-rent/{area.lower().replace(' ', '-')}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    property_cards = soup.find_all('div', class_=['property-card', 'listing-item', 'property-item'])
                    
                    for card in property_cards[:5]:
                        try:
                            title_elem = card.find(['h3', 'h4', 'h2'], class_=['title', 'property-title'])
                            title = title_elem.get_text(strip=True) if title_elem else "No title"
                            
                            price_elem = card.find(['span', 'div'], class_=['price', 'amount'])
                            price_text = price_elem.get_text(strip=True) if price_elem else "0"
                            price = extract_price(price_text)
                            
                            location_elem = card.find(['span', 'div'], class_=['location', 'address'])
                            location = location_elem.get_text(strip=True) if location_elem else area
                            
                            desc_elem = card.find(['p', 'div'], class_=['description', 'excerpt'])
                            description = desc_elem.get_text(strip=True) if desc_elem else "No description"
                            
                            link_elem = card.find('a', href=True)
                            url = link_elem['href'] if link_elem else ""
                            if url and not url.startswith('http'):
                                url = f"https://www.buyrentkenya.com{url}"
                            
                            bedrooms = extract_bedrooms(title + " " + description)
                            property_type = extract_property_type(title + " " + description)
                            
                            listings.append(HousingListing(
                                title=title,
                                price=price,
                                location=location,
                                area=area,
                                bedrooms=bedrooms,
                                property_type=property_type,
                                description=description[:200] + "..." if len(description) > 200 else description,
                                contact=None,
                                url=url,
                                source="Fallback Scraping",
                                images=[]
                            ))
                        except Exception as e:
                            continue
                            
    except Exception as e:
        print(f"Error in fallback scraping for {area}: {str(e)}")
    
    return listings

def extract_price(price_text: str) -> Optional[int]:
    """Extract numeric price from text"""
    try:
        price_text = price_text.replace(',', '').replace(' ', '')
        numbers = re.findall(r'\d+', price_text)
        if numbers:
            price = int(numbers[0])
            if 'million' in price_text.lower() or 'm' in price_text.lower():
                price *= 1000000
            elif 'k' in price_text.lower() and price < 1000:
                price *= 1000
            return price
    except:
        pass
    return None

def extract_bedrooms(text: str) -> Optional[int]:
    """Extract number of bedrooms from text"""
    try:
        bedroom_patterns = [
            r'(\d+)\s*bed',
            r'(\d+)\s*br',
            r'(\d+)\s*bedroom',
            r'(\d+)br',
            r'(\d+)bed'
        ]
        
        for pattern in bedroom_patterns:
            match = re.search(pattern, text.lower())
            if match:
                return int(match.group(1))
    except:
        pass
    return None

def extract_property_type(text: str) -> str:
    """Extract property type from text"""
    text_lower = text.lower()
    
    if any(word in text_lower for word in ['studio', 'bedsitter', 'bed sitter']):
        return 'studio'
    elif any(word in text_lower for word in ['apartment', 'flat']):
        return 'apartment'
    elif any(word in text_lower for word in ['house', 'bungalow', 'maisonette']):
        return 'house'
    elif any(word in text_lower for word in ['villa', 'mansion']):
        return 'villa'
    else:
        return 'apartment'

@app.websocket("/ws/scraping-progress")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass

@app.post("/scrape-listings-ai", response_model=List[HousingListing])
async def scrape_housing_listings_ai(request: HousingListingRequest):
    """AI-powered scraping with progress tracking and user-configurable API keys"""
    try:
        all_listings = []
        
        effective_api_key = request.api_key or OPENAI_API_KEY
        if not effective_api_key and not USE_LOCAL_LLM:
            raise HTTPException(
                status_code=400, 
                detail="AI scraping requires an API key. Please provide your OpenAI API key."
            )
        
        sites_to_scrape = []
        for area in request.areas:
            sites_to_scrape.extend([
                f"https://www.buyrentkenya.com/houses-for-rent/{area.lower().replace(' ', '-')}",
                f"https://www.pigiame.co.ke/houses-apartments-for-rent/{area.lower().replace(' ', '-')}",
                f"https://www.jiji.co.ke/houses-apartments-for-rent/{area.lower().replace(' ', '-')}"
            ])
        
        for site_url in sites_to_scrape:
            area = request.areas[sites_to_scrape.index(site_url) // 3]
            listings = await ai_scrape_housing_site(site_url, area, request.api_key)
            all_listings.extend(listings)
        
        filtered_listings = []
        for listing in all_listings:
            if request.min_budget and listing.price and listing.price < request.min_budget:
                continue
            if request.max_budget and listing.price and listing.price > request.max_budget:
                continue
            if request.bedrooms and listing.bedrooms and listing.bedrooms != request.bedrooms:
                continue
            if request.property_type != "any" and listing.property_type != request.property_type:
                continue
            
            filtered_listings.append(listing)
        
        seen = set()
        unique_listings = []
        for listing in filtered_listings:
            key = (listing.title.lower(), listing.price, listing.location.lower())
            if key not in seen:
                seen.add(key)
                unique_listings.append(listing)
        
        unique_listings.sort(key=lambda x: x.price or 0)
        return unique_listings[:50]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI scraping failed: {str(e)}")

@app.get("/ai-config-status")
async def get_ai_config_status():
    """Check AI configuration status"""
    return {
        "openai_configured": bool(OPENAI_API_KEY),
        "local_llm_enabled": USE_LOCAL_LLM,
        "ollama_url": OLLAMA_BASE_URL if USE_LOCAL_LLM else None,
        "max_listings": MAX_LISTINGS_PER_SITE,
        "timeout": SCRAPING_TIMEOUT
    }

@app.post("/scrape-listings", response_model=List[HousingListing])
async def scrape_housing_listings(request: HousingListingRequest):
    """Legacy scraping endpoint for backward compatibility"""
    return await scrape_housing_listings_ai(request)

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Kenya Housing Location Finder API"}
