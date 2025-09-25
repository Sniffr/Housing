import { useState, useEffect } from 'react'
import { MapContainer, TileLayer, Marker, Popup, Polygon, useMap } from 'react-leaflet'
import { LatLngExpression } from 'leaflet'
import { Search, MapPin, Clock, Car, Home, Calendar, DollarSign, Building, Bed } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import 'leaflet/dist/leaflet.css'
import './leaflet-setup'
import './App.css'

interface LocationResult {
  display_name: string
  lat: number
  lng: number
  place_id: string
}

interface IsochronePoint {
  lat: number
  lng: number
}

interface NamedArea {
  name: string
  lat: number
  lng: number
  commute_time_minutes: number
  description: string
}

interface HousingListing {
  title: string
  price: number | null
  location: string
  area: string
  bedrooms: number | null
  property_type: string
  description: string
  contact: string | null
  url: string
  source: string
  images: string[]
}

function MapUpdater({ center, zoom }: { center: LatLngExpression, zoom: number }) {
  const map = useMap()
  
  useEffect(() => {
    map.setView(center, zoom)
  }, [map, center, zoom])
  
  return null
}

function App() {
  const [workLocation, setWorkLocation] = useState<string>('')
  const [searchResults, setSearchResults] = useState<LocationResult[]>([])
  const [selectedLocation, setSelectedLocation] = useState<LocationResult | null>(null)
  const [commuteTime, setCommuteTime] = useState<number[]>([20])
  const [transportMode, setTransportMode] = useState<string>('driving')
  const [workStartTime, setWorkStartTime] = useState<string>('08:00')
  const [workEndTime, setWorkEndTime] = useState<string>('17:00')
  const [isochrone, setIsochrone] = useState<IsochronePoint[]>([])
  const [suggestedAreas, setSuggestedAreas] = useState<NamedArea[]>([])
  const [minBudget, setMinBudget] = useState<number[]>([10000])
  const [maxBudget, setMaxBudget] = useState<number[]>([100000])
  const [propertyType, setPropertyType] = useState<string>('any')
  const [bedrooms, setBedrooms] = useState<string>('any')
  const [housingListings, setHousingListings] = useState<HousingListing[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [isScrapingListings, setIsScrapingListings] = useState<boolean>(false)
  const [mapCenter, setMapCenter] = useState<LatLngExpression>([-1.2921, 36.8219])
  const [mapZoom, setMapZoom] = useState<number>(7)
  const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

  const searchLocations = async () => {
    if (!workLocation.trim()) return

    setIsLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/search-locations`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: workLocation,
          country: 'Kenya'
        }),
      })

      if (response.ok) {
        const results = await response.json()
        setSearchResults(results)
      }
    } catch (error) {
      console.error('Location search failed:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const selectLocation = async (location: LocationResult) => {
    setSelectedLocation(location)
    setSearchResults([])
    
    setMapCenter([location.lat, location.lng])
    setMapZoom(12)
    
    setIsLoading(true)
    try {
      const isochroneResponse = await fetch(`${API_BASE_URL}/calculate-isochrone`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          work_lat: location.lat,
          work_lng: location.lng,
          max_commute_minutes: commuteTime[0],
          transport_mode: transportMode,
          work_start_time: workStartTime,
          work_end_time: workEndTime
        }),
      })

      if (isochroneResponse.ok) {
        const isochroneData = await isochroneResponse.json()
        setIsochrone(isochroneData)
      }

      const areasResponse = await fetch(`${API_BASE_URL}/suggest-areas`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          work_lat: location.lat,
          work_lng: location.lng,
          max_commute_minutes: commuteTime[0],
          transport_mode: transportMode,
          work_start_time: workStartTime,
          work_end_time: workEndTime
        }),
      })

      if (areasResponse.ok) {
        const areasData = await areasResponse.json()
        setSuggestedAreas(areasData)
      }
    } catch (error) {
      console.error('Location calculation failed:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const updateCommute = async () => {
    if (!selectedLocation) return

    setIsLoading(true)
    try {
      const isochroneResponse = await fetch(`${API_BASE_URL}/calculate-isochrone`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          work_lat: selectedLocation.lat,
          work_lng: selectedLocation.lng,
          max_commute_minutes: commuteTime[0],
          transport_mode: transportMode,
          work_start_time: workStartTime,
          work_end_time: workEndTime
        }),
      })

      if (isochroneResponse.ok) {
        const isochroneData = await isochroneResponse.json()
        setIsochrone(isochroneData)
      }

      const areasResponse = await fetch(`${API_BASE_URL}/suggest-areas`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          work_lat: selectedLocation.lat,
          work_lng: selectedLocation.lng,
          max_commute_minutes: commuteTime[0],
          transport_mode: transportMode,
          work_start_time: workStartTime,
          work_end_time: workEndTime
        }),
      })

      if (areasResponse.ok) {
        const areasData = await areasResponse.json()
        setSuggestedAreas(areasData)
      }
    } catch (error) {
      console.error('Commute calculation failed:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const scrapeHousingListings = async () => {
    if (suggestedAreas.length === 0) return

    setIsScrapingListings(true)
    try {
      const areaNames = suggestedAreas.map(area => area.name)
      
      const response = await fetch(`${API_BASE_URL}/scrape-listings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          areas: areaNames,
          min_budget: minBudget[0],
          max_budget: maxBudget[0],
          property_type: propertyType,
          bedrooms: bedrooms === 'any' ? null : parseInt(bedrooms)
        }),
      })

      if (response.ok) {
        const listings = await response.json()
        setHousingListings(listings)
      }
    } catch (error) {
      console.error('Housing listing scraping failed:', error)
    } finally {
      setIsScrapingListings(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="container mx-auto p-4">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            Kenya Housing Location Finder
          </h1>
          <p className="text-gray-600">
            Find the perfect place to live based on your work location and commute preferences
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-1">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Search className="h-5 w-5" />
                  Search Work Location
                </CardTitle>
                <CardDescription>
                  Enter your workplace in Kenya
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="work-location">Work Location</Label>
                  <div className="flex gap-2">
                    <Input
                      id="work-location"
                      placeholder="e.g., Westlands, Nairobi"
                      value={workLocation}
                      onChange={(e) => setWorkLocation(e.target.value)}
                      onKeyPress={(e) => e.key === 'Enter' && searchLocations()}
                    />
                    <Button onClick={searchLocations} disabled={isLoading}>
                      <Search className="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                {searchResults.length > 0 && (
                  <div className="space-y-2">
                    <Label>Search Results</Label>
                    <div className="max-h-40 overflow-y-auto space-y-1">
                      {searchResults.map((result) => (
                        <Button
                          key={result.place_id}
                          variant="outline"
                          className="w-full text-left justify-start h-auto p-2"
                          onClick={() => selectLocation(result)}
                        >
                          <MapPin className="h-4 w-4 mr-2 flex-shrink-0" />
                          <span className="text-sm truncate">{result.display_name}</span>
                        </Button>
                      ))}
                    </div>
                  </div>
                )}

                {selectedLocation && (
                  <div className="space-y-4 pt-4 border-t">
                    <div className="space-y-2">
                      <Label className="flex items-center gap-2">
                        <Calendar className="h-4 w-4" />
                        Work Schedule
                      </Label>
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <Label className="text-xs text-gray-500">Start Time</Label>
                          <Input
                            type="time"
                            value={workStartTime}
                            onChange={(e) => setWorkStartTime(e.target.value)}
                          />
                        </div>
                        <div>
                          <Label className="text-xs text-gray-500">End Time</Label>
                          <Input
                            type="time"
                            value={workEndTime}
                            onChange={(e) => setWorkEndTime(e.target.value)}
                          />
                        </div>
                      </div>
                    </div>

                    <div className="space-y-2">
                      <Label className="flex items-center gap-2">
                        <Clock className="h-4 w-4" />
                        Max Commute Time: {commuteTime[0]} minutes
                      </Label>
                      <Slider
                        value={commuteTime}
                        onValueChange={setCommuteTime}
                        max={60}
                        min={5}
                        step={5}
                        className="w-full"
                      />
                    </div>

                    <div className="space-y-2">
                      <Label className="flex items-center gap-2">
                        <Car className="h-4 w-4" />
                        Transport Mode
                      </Label>
                      <Select value={transportMode} onValueChange={setTransportMode}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="driving">Driving</SelectItem>
                          <SelectItem value="public_transport">Public Transport</SelectItem>
                          <SelectItem value="walking">Walking</SelectItem>
                          <SelectItem value="cycling">Cycling</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <Button onClick={updateCommute} disabled={isLoading} className="w-full">
                      Update Commute Area
                    </Button>

                    {suggestedAreas.length > 0 && (
                      <div className="space-y-4 pt-4 border-t">
                        <div className="space-y-2">
                          <Label className="flex items-center gap-2">
                            <Home className="h-4 w-4" />
                            Suggested Areas ({suggestedAreas.length})
                          </Label>
                          <div className="max-h-32 overflow-y-auto space-y-2">
                            {suggestedAreas.map((area) => (
                              <div
                                key={area.name}
                                className="p-2 border rounded-lg hover:bg-gray-50 cursor-pointer"
                                onClick={() => {
                                  setMapCenter([area.lat, area.lng])
                                  setMapZoom(13)
                                }}
                              >
                                <div className="flex justify-between items-start">
                                  <div>
                                    <h4 className="font-medium text-xs">{area.name}</h4>
                                    <p className="text-xs text-gray-500 mt-1 truncate">{area.description}</p>
                                  </div>
                                  <span className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded">
                                    {area.commute_time_minutes}min
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>

                        <div className="space-y-4 pt-4 border-t">
                          <Label className="flex items-center gap-2">
                            <DollarSign className="h-4 w-4" />
                            Budget Range (KSh)
                          </Label>
                          
                          <div className="space-y-2">
                            <Label className="text-xs text-gray-500">
                              Min Budget: KSh {minBudget[0].toLocaleString()}
                            </Label>
                            <Slider
                              value={minBudget}
                              onValueChange={setMinBudget}
                              max={200000}
                              min={5000}
                              step={5000}
                              className="w-full"
                            />
                          </div>

                          <div className="space-y-2">
                            <Label className="text-xs text-gray-500">
                              Max Budget: KSh {maxBudget[0].toLocaleString()}
                            </Label>
                            <Slider
                              value={maxBudget}
                              onValueChange={setMaxBudget}
                              max={500000}
                              min={10000}
                              step={10000}
                              className="w-full"
                            />
                          </div>

                          <div className="space-y-2">
                            <Label className="flex items-center gap-2">
                              <Building className="h-4 w-4" />
                              Property Type
                            </Label>
                            <Select value={propertyType} onValueChange={setPropertyType}>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="any">Any</SelectItem>
                                <SelectItem value="apartment">Apartment</SelectItem>
                                <SelectItem value="house">House</SelectItem>
                                <SelectItem value="studio">Studio</SelectItem>
                                <SelectItem value="villa">Villa</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>

                          <div className="space-y-2">
                            <Label className="flex items-center gap-2">
                              <Bed className="h-4 w-4" />
                              Bedrooms
                            </Label>
                            <Select value={bedrooms} onValueChange={setBedrooms}>
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="any">Any</SelectItem>
                                <SelectItem value="1">1 Bedroom</SelectItem>
                                <SelectItem value="2">2 Bedrooms</SelectItem>
                                <SelectItem value="3">3 Bedrooms</SelectItem>
                                <SelectItem value="4">4+ Bedrooms</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>

                          <Button 
                            onClick={scrapeHousingListings} 
                            disabled={isScrapingListings} 
                            className="w-full"
                          >
                            {isScrapingListings ? 'Finding Listings...' : 'Find Housing Listings'}
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Map View</CardTitle>
                <CardDescription>
                  {selectedLocation 
                    ? `Showing areas within ${commuteTime[0]} minutes of ${selectedLocation.display_name.split(',')[0]}`
                    : 'Search for your work location to see commute areas'
                  }
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-96 w-full rounded-lg overflow-hidden">
                  <MapContainer
                    center={mapCenter}
                    zoom={mapZoom}
                    style={{ height: '100%', width: '100%' }}
                  >
                    <MapUpdater center={mapCenter} zoom={mapZoom} />
                    <TileLayer
                      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />
                    
                    {selectedLocation && (
                      <Marker position={[selectedLocation.lat, selectedLocation.lng]}>
                        <Popup>
                          <div className="text-center">
                            <strong>Work Location</strong><br />
                            {selectedLocation.display_name.split(',')[0]}
                          </div>
                        </Popup>
                      </Marker>
                    )}

                    {suggestedAreas.map((area) => (
                      <Marker
                        key={area.name}
                        position={[area.lat, area.lng]}
                      >
                        <Popup>
                          <div className="text-center">
                            <strong>{area.name}</strong><br />
                            <span className="text-sm text-gray-600">{area.description}</span><br />
                            <span className="text-sm font-medium text-blue-600">
                              {area.commute_time_minutes} min commute
                            </span>
                          </div>
                        </Popup>
                      </Marker>
                    ))}

                    {isochrone.length > 0 && (
                      <Polygon
                        positions={isochrone.map(point => [point.lat, point.lng])}
                        pathOptions={{
                          color: '#3b82f6',
                          fillColor: '#3b82f6',
                          fillOpacity: 0.2,
                          weight: 2
                        }}
                      >
                        <Popup>
                          <div className="text-center">
                            <strong>Commute Area</strong><br />
                            Within {commuteTime[0]} minutes by {transportMode}<br />
                            <span className="text-xs text-gray-500">
                              Based on {workStartTime} work start time
                            </span>
                          </div>
                        </Popup>
                      </Polygon>
                    )}
                  </MapContainer>
                </div>
              </CardContent>
            </Card>

            {housingListings.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Housing Listings ({housingListings.length})</CardTitle>
                  <CardDescription>
                    Available properties in your preferred areas within budget
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="max-h-96 overflow-y-auto space-y-3">
                    {housingListings.map((listing, index) => (
                      <div key={index} className="border rounded-lg p-4 hover:bg-gray-50">
                        <div className="flex justify-between items-start mb-2">
                          <h4 className="font-medium text-sm line-clamp-2">{listing.title}</h4>
                          <div className="text-right">
                            {listing.price && (
                              <span className="font-bold text-green-600">
                                KSh {listing.price.toLocaleString()}
                              </span>
                            )}
                            <div className="text-xs text-gray-500 mt-1">{listing.source}</div>
                          </div>
                        </div>
                        
                        <div className="flex items-center gap-4 text-xs text-gray-600 mb-2">
                          <span className="flex items-center gap-1">
                            <MapPin className="h-3 w-3" />
                            {listing.area}
                          </span>
                          {listing.bedrooms && (
                            <span className="flex items-center gap-1">
                              <Bed className="h-3 w-3" />
                              {listing.bedrooms} bed{listing.bedrooms > 1 ? 's' : ''}
                            </span>
                          )}
                          <span className="flex items-center gap-1">
                            <Building className="h-3 w-3" />
                            {listing.property_type}
                          </span>
                        </div>
                        
                        <p className="text-xs text-gray-700 mb-3 line-clamp-2">
                          {listing.description}
                        </p>
                        
                        {listing.url && (
                          <Button 
                            variant="outline" 
                            size="sm" 
                            onClick={() => window.open(listing.url, '_blank')}
                            className="text-xs"
                          >
                            View Details
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
