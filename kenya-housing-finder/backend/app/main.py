from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
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

async def scrape_buyrentkenya(session: aiohttp.ClientSession, area: str, max_budget: Optional[int] = None) -> List[HousingListing]:
    """Scrape housing listings from BuyRentKenya"""
    listings = []
    try:
        search_url = f"https://www.buyrentkenya.com/houses-for-rent/{area.lower().replace(' ', '-')}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        async with session.get(search_url, headers=headers) as response:
            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                property_cards = soup.find_all('div', class_=['property-card', 'listing-item', 'property-item'])
                
                for card in property_cards[:10]:  # Limit to 10 listings per area
                    try:
                        title_elem = card.find(['h3', 'h4', 'h2'], class_=['title', 'property-title'])
                        title = title_elem.get_text(strip=True) if title_elem else "No title"
                        
                        price_elem = card.find(['span', 'div'], class_=['price', 'amount'])
                        price_text = price_elem.get_text(strip=True) if price_elem else "0"
                        price = extract_price(price_text)
                        
                        if max_budget and price and price > max_budget:
                            continue
                        
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
                            source="BuyRentKenya",
                            images=[]
                        ))
                    except Exception as e:
                        continue
                        
    except Exception as e:
        print(f"Error scraping BuyRentKenya for {area}: {str(e)}")
    
    return listings

async def scrape_pigikenya(session: aiohttp.ClientSession, area: str, max_budget: Optional[int] = None) -> List[HousingListing]:
    """Scrape housing listings from PigiaKenya"""
    listings = []
    try:
        search_url = f"https://www.pigiame.co.ke/houses-apartments-for-rent/{area.lower().replace(' ', '-')}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        async with session.get(search_url, headers=headers) as response:
            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                property_cards = soup.find_all('div', class_=['listing-card', 'ad-item', 'property-listing'])
                
                for card in property_cards[:10]:  # Limit to 10 listings per area
                    try:
                        title_elem = card.find(['h3', 'h4', 'h2'])
                        title = title_elem.get_text(strip=True) if title_elem else "No title"
                        
                        price_elem = card.find(['span', 'div'], string=re.compile(r'KSh|Ksh|ksh'))
                        price_text = price_elem.get_text(strip=True) if price_elem else "0"
                        price = extract_price(price_text)
                        
                        if max_budget and price and price > max_budget:
                            continue
                        
                        location_elem = card.find(['span', 'div'], class_=['location'])
                        location = location_elem.get_text(strip=True) if location_elem else area
                        
                        desc_elem = card.find(['p', 'div'], class_=['description'])
                        description = desc_elem.get_text(strip=True) if desc_elem else "No description"
                        
                        link_elem = card.find('a', href=True)
                        url = link_elem['href'] if link_elem else ""
                        if url and not url.startswith('http'):
                            url = f"https://www.pigiame.co.ke{url}"
                        
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
                            source="PigiaKenya",
                            images=[]
                        ))
                    except Exception as e:
                        continue
                        
    except Exception as e:
        print(f"Error scraping PigiaKenya for {area}: {str(e)}")
    
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

@app.post("/scrape-listings", response_model=List[HousingListing])
async def scrape_housing_listings(request: HousingListingRequest):
    """Scrape housing listings from multiple sources for specified areas"""
    try:
        all_listings = []
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            for area in request.areas:
                tasks.append(scrape_buyrentkenya(session, area, request.max_budget))
                tasks.append(scrape_pigikenya(session, area, request.max_budget))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, list):
                    all_listings.extend(result)
        
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
        
        filtered_listings.sort(key=lambda x: x.price or 0)
        
        return filtered_listings[:50]  # Return top 50 results
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Listing scraping failed: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Kenya Housing Location Finder API"}
