
# Weather and Population Data Pipeline

## Overview

This project combines population data for 70 cities with current weather information from the Open-Meteo API. It uses Python and Pandas to process the data, saves the merged output as a CSV file, and optionally uploads the results to Google BigQuery.

## Project Structure

```text
weather_pipeline/
├── data/                 # Local input and output CSV files (ignored by Git)
├── scripts/
│   └── main.py           # Main pipeline script
├── .gitignore
├── requirements.txt
└── README.md
```

## Features

- Loads city population, latitude, and longitude from a CSV file.
- Fetches current temperature and wind speed for each city's coordinates.
- Converts temperature from Celsius to Fahrenheit.
- Categorizes temperatures as Cold, Mild, Hot, or Unavailable.
- Preserves city records when individual weather requests fail.
- Saves the processed dataset as `data/weather_merged.csv`.
- Supports uploading results to Google BigQuery.

## Requirements

- Python 3
- An Open-Meteo API connection
- Google Cloud credentials and BigQuery permissions for optional uploads

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Place the input file at:

```text
data/population.csv
```

The CSV must contain these columns:

- `City`
- `Country`
- `Population`
- `Latitude`
- `Longitude`

## Run the Pipeline

From the project root, run:

```bash
python scripts/main.py
```

The merged output is saved to:

```text
data/weather_merged.csv
```

Weather requests that fail are marked in `Weather_Status`; their city records remain in the output.

## BigQuery Configuration

The script can use a service-account key at `scripts/gcp-key.json` or Application Default Credentials. Configure the required Google Cloud permissions before enabling uploads.

**Security:** Never commit service-account keys, `.env` files, virtual environments, or local data files to Git.
