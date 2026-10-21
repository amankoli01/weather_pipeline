
import os
import time
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from google.cloud import bigquery
from google.auth.exceptions import DefaultCredentialsError


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "population.csv"
OUTPUT_FILE = ROOT / "data" / "weather_merged.csv"
CREDENTIALS_FILE = ROOT / "scripts" / "gcp-key.json"

PROJECT_ID = "weather-demographics-bootcamp"
DATASET_ID = "global_weather_data"
TABLE_ID = "current_weather_stats"

BIGQUERY_TABLE = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


# --------------------------------------------------
# HTTP SESSION WITH RETRIES
# --------------------------------------------------

def create_session():
    session = requests.Session()

    retries = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )

    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


# --------------------------------------------------
# LOAD ALL 70 POPULATION RECORDS
# --------------------------------------------------

def load_population():
    print("Loading population data...")

    if not DATA_FILE.exists():
        raise FileNotFoundError(f"CSV not found: {DATA_FILE}")

    df = pd.read_csv(DATA_FILE)

    required = {"City", "Country", "Population", "Latitude", "Longitude"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing CSV columns: {sorted(missing)}")

    df["City"] = df["City"].astype(str).str.strip()
    df["Country"] = df["Country"].astype(str).str.strip()

    df["Population"] = pd.to_numeric(
        df["Population"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )

    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")

    df = df.dropna(
        subset=["City", "Country", "Population", "Latitude", "Longitude"]
    ).copy()

    df["Population"] = df["Population"].astype("int64")

    print(f"Valid population records loaded: {len(df)}")

    if len(df) != 70:
        print(f"Warning: Expected 70 records but loaded {len(df)}.")

    return df.reset_index(drop=True)


# --------------------------------------------------
# FETCH WEATHER FOR EVERY CITY IN THE CSV
# --------------------------------------------------

def fetch_weather(population_df):
    session = create_session()
    records = []

    total = len(population_df)
    print(f"\nFetching weather for all {total} cities...")

    for index, row in population_df.iterrows():
        city = row["City"]
        country = row["Country"]
        latitude = row["Latitude"]
        longitude = row["Longitude"]

        weather = {
            "City": city,
            "Country": country,
            "Latitude": latitude,
            "Longitude": longitude,
            "Temperature_C": None,
            "Wind_Speed_kmh": None,
            "Observation_Time": None,
            "Weather_Status": "Failed",
        }

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,wind_speed_10m",
            "timezone": "auto",
        }

        try:
            response = session.get(
                WEATHER_URL,
                params=params,
                timeout=(15, 45),
            )
            response.raise_for_status()

            current = response.json().get("current", {})

            temperature = current.get("temperature_2m")
            wind_speed = current.get("wind_speed_10m")

            if temperature is None or wind_speed is None:
                raise ValueError("Temperature or wind speed missing")           
            temperature = current.get("temperature_2m")
            wind_speed = current.get("wind_speed_10m")

            if temperature is None or wind_speed is None:
                raise ValueError("Temperature or wind speed missing")

            if (
                isinstance(temperature, bool)
                or isinstance(wind_speed, bool)
            ):
                raise ValueError("Temperature or wind speed is invalid")

            try:
                temperature = float(temperature)
                wind_speed = float(wind_speed)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "Temperature or wind speed is not numeric"
                ) from error

            weather.update({
                "Temperature_C": temperature,
                "Wind_Speed_kmh": wind_speed,
                "Observation_Time": current.get("time"),
                "Weather_Status": "Success",
            })

            print(f"[{index + 1}/{total}] Fetched: {city}, {country}")

        except (requests.RequestException, ValueError, KeyError) as error:
            print(f"[{index + 1}/{total}] Failed: {city} - {error}")

        records.append(weather)
        time.sleep(0.2)

    session.close()

    result = pd.DataFrame(records)

    successful = (result["Weather_Status"] == "Success").sum()
    failed = total - successful

    print(f"\nTotal cities: {total}")
    print(f"Successful weather requests: {successful}")
    print(f"Failed weather requests: {failed}")

    return result


# --------------------------------------------------
# MERGE WEATHER WITH THE ORIGINAL POPULATION DATA
# --------------------------------------------------

def transform_data(population_df, weather_df):
    print("\nMerging weather with population data...")

    # Each weather request uses the same city coordinates and name
    # as the corresponding CSV row, so merge by city and country.
    merged = population_df.merge(
        weather_df,
        on=["City", "Country", "Latitude", "Longitude"],
        how="left",
        validate="one_to_one",
        suffixes=("_population", ""),
    )

    merged["Temperature_C"] = pd.to_numeric(
        merged["Temperature_C"], errors="coerce"
    )
    merged["Wind_Speed_kmh"] = pd.to_numeric(
        merged["Wind_Speed_kmh"], errors="coerce"
    )

    merged["Temperature_F"] = (
        merged["Temperature_C"] * 9 / 5 + 32
    ).round(2)

    merged["Temperature_Category"] = "Unavailable"

    valid = merged["Temperature_C"].notna()

    merged.loc[
        valid & (merged["Temperature_C"] < 10),
        "Temperature_Category",
    ] = "Cold"

    merged.loc[
        valid
        & (merged["Temperature_C"] >= 10)
        & (merged["Temperature_C"] <= 25),
        "Temperature_Category",
    ] = "Mild"

    merged.loc[
        valid & (merged["Temperature_C"] > 25),
        "Temperature_Category",
    ] = "Hot"

    columns = [
        "City",
        "Country",
        "Population",
        "Latitude",
        "Longitude",
        "Temperature_C",
        "Temperature_F",
        "Wind_Speed_kmh",
        "Observation_Time",
        "Temperature_Category",
        "Weather_Status",
    ]

    merged = merged[columns]

    print(f"Final dataset rows: {len(merged)}")
    print(f"Cities with weather: {valid.sum()}")
    print(f"Cities without weather: {(~valid).sum()}")

    return merged


# --------------------------------------------------
# SAVE THE OUTPUT CSV
# --------------------------------------------------

def save_output(df):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)

    print(f"\nCSV saved: {OUTPUT_FILE}")
    print(f"Saved rows: {len(df)}")


# --------------------------------------------------
# UPLOAD TO BIGQUERY
# --------------------------------------------------

def upload_to_bigquery(df):
    key_exists = CREDENTIALS_FILE.exists()
    adc_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if not key_exists and not adc_path:
        print("\nBigQuery upload skipped: credentials not configured.")
        print("The 70-row CSV has been saved locally.")
        return

    try:
        if key_exists:
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_file(
                str(CREDENTIALS_FILE)
            )
            client = bigquery.Client(
                project=PROJECT_ID,
                credentials=credentials,
            )
        else:
            client = bigquery.Client(project=PROJECT_ID)

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=True,
        )

        job = client.load_table_from_dataframe(
            df,
            BIGQUERY_TABLE,
            job_config=job_config,
        )
        job.result()

        print(f"BigQuery upload successful: {BIGQUERY_TABLE}")
        print(f"Rows uploaded: {len(df)}")

    except DefaultCredentialsError:
        print("BigQuery upload skipped: Google credentials are missing or invalid.")
    except Exception as error:
        print(f"BigQuery upload failed: {error}")
        print("Your local CSV is still saved.")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print("=" * 70)
    print("WEATHER AND POPULATION PIPELINE")
    print("=" * 70)

    population_df = load_population()
    weather_df = fetch_weather(population_df)

    merged_df = transform_data(population_df, weather_df)

    print("\nFinal dataset preview:")
    print(merged_df.head(10).to_string(index=False))

    save_output(merged_df)
    upload_to_bigquery(merged_df)

    print("\nPipeline finished.")


if __name__ == "__main__":
    main()
