# Cheapest Route Finder — TrueForge Agent Doctor demo

Doctor (live scorer) findings: readme_sections, rating, description, handle, success_rate, eval_rate, starter_prompts
Agent findings: readme_sections, description, rating, success_rate, eval_rate, handle, starter_prompts

## New description

Cheapest Route Finder: compares car, train, bus, and flight prices between two places and picks the cheapest option.

## New keywords

cheapest route, route finder, travel cost comparison, compare transport options, budget travel

## New starter prompts

- What is the cheapest route from Rome to Milan tomorrow?
- Can you compare car, train, bus, and flight prices from Paris to Amsterdam?
- How much is the cheapest trip from London to Edinburgh on 2025-08-15?
- Which is cheaper today, the train or the bus from Berlin to Munich?

## New README

# Cheapest Route Finder

## Summary

Cheapest Route Finder is a travel agent that web-searches car, train, bus, and flight options between two places and highlights the cheapest route overall. It is built for travelers on a budget who want a quick travel cost comparison before deciding how to go. Provide an origin, a destination, and an optional date, and it returns normalized costs, distances, and durations for every mode in one view.

## Key features

- Web-searches car, train, bus, and flight options between cities or landmarks
- Compares all modes side-by-side with normalized costs, distances, and durations
- Date-aware: understands today, tomorrow, and YYYY-MM-DD, defaulting to today
- Highlights the cheapest overall option across every mode of transport
- Works for any pair of places, with no fixed routes or sign-up

## Usage

Send a message with your origin, destination, and optionally a travel date such as today, tomorrow, or a YYYY-MM-DD date. The agent searches current options and replies with a side-by-side comparison plus its cheapest pick. Example exchange:

    User: Please provide me cheapest route for Rome to Milan tomorrow.
    Agent: Car: 573 km, 5.8 h, ~120 EUR. Train: 2.9 h, 28 EUR. Bus: 7.1 h, 9 EUR. Flight: 1.2 h, 48 EUR. Cheapest overall: Bus at 9.00 EUR.

## Use cases

This route finder serves budget travelers, commuters weighing a bus against a train, trip planners estimating costs, and anyone who wants to compare transport options for an upcoming journey. It is practical for budget travel planning between any two cities or landmarks, especially when you want the cheapest way to go without visiting several sites yourself.

## Limitations

The agent does not book tickets and does not guarantee prices. It uses no maps or booking APIs and does not show live flight status, so all figures are approximations drawn from web search results at the time of your request. Prices and schedules change quickly, so treat every number as an estimate and confirm details with the operator before purchasing.

## Metadata

- Version: 1.0.0
- Category: Travel
- Model: OpenAI gpt-4o-mini with web search preview
- Data source: live web search results; no maps or booking APIs

