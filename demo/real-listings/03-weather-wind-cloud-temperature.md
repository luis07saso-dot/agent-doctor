# Weather Wind Cloud Temperature — TrueForge Agent Doctor demo

Doctor (live scorer) findings: readme_sections, rating, description, responsive, handle, starter_prompts
Agent findings: responsive, readme_sections, description, rating, handle, starter_prompts

## New description

Current weather, 5-day forecasts, city geocoding, and weather by coordinates for travelers and planners.

## New keywords

current weather, weather forecast, geocoding, 5-day forecast, wind speed, cloud coverage

## New starter prompts

- What is the current weather in Bratislava?
- Give me the weather forecast for tomorrow for Kosice?
- What are the coordinates of Paris?
- What is the weather at coordinates 42.0, 19.1?

## New README

# Weather Wind Cloud Temperature

## Summary

This agent answers weather questions for anyone who needs a quick, reliable check of conditions in a named city or at a pair of coordinates. It returns the current weather, a 5-day forecast with 3-hour steps, and geocoding that translates city names into geographical coordinates. Every reply uses fixed physical units: temperature in celsius, wind speed in meters per second, and cloud coverage in %.

## Key features

- Current weather for any named city.
- Weather forecast up to 5 days ahead with 3-hour steps.
- Geocoding: a city name translated into geographical coordinates (latitude and longitude).
- Weather by coordinates, for places without a well-known name.
- Fixed units in every reply: temperature in celsius, wind speed in meters per second, cloud coverage in %.

## Usage

Send a plain-language question in chat and the agent replies with the requested numbers. You can ask for the current weather, a weather forecast, the coordinates of a city, or weather at given coordinates. For example:

    User: What is the current weather in Bratislava?
    Agent: In Bratislava it is currently 21.4 celsius with wind speed 3.2 meters per second and cloud coverage 40%.
    User: Give me the coordinates of Paris.
    Agent: Paris is at geographical coordinates 48.8566, 2.3522.

## Use cases

Travelers check conditions before a trip, cyclists and runners pick a dry 3-hour window, and drone or event planners watch cloud coverage and wind speed. Developers use the geocoding replies to feed coordinates into maps or routing tools, and anyone without a city name can query weather by coordinates directly.

## Limitations

The forecast horizon is capped at 5 days with 3-hour steps, so sub-hour nowcasts and long-range outlooks are not available. Units are fixed (celsius, meters per second, %) and cannot be switched to other systems. Geocoding works best with well-known city names; small villages, districts, or misspelled names may fail or resolve to the nearest match. Data comes from a single external provider, so brief outages or small approximations are possible.

## Metadata

- Version: 1.0
- Category: Weather
- Source of data: https://api.openweathermap.org/
