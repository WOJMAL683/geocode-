import csv
import requests

API_URL = "https://nominatim.openstreetmap.org/search"

def geocode(address):
    params = {"q": address, "format": "json", "limit": 1}
    r = requests.get(API_URL, params=params, headers={"User-Agent": "geo-app"})
    if r.status_code == 200 and r.json():
        lat = r.json()[0]["lat"]
        lon = r.json()[0]["lon"]
        return f"POINT({lon} {lat})"
    return ""

input_file = "wejscie.csv"
output_file = "wyjscie.csv"

with open(input_file, newline="", encoding="utf-8") as fin:
    reader = csv.reader(fin, delimiter=";")
    headers = next(reader)  # zachowujemy oryginalne nagłówki
    rows = list(reader)

# znajdź indeks kolumny geometry
geometry_idx = headers.index("geometry")

# aktualizacja tylko kolumny geometry
for row in rows:
    if any(row):  # pomiń puste wiersze
        # przykład adresu: street_name (2), house_number (3), city_name (4)
        address = f"{row[2]} {row[3]}, {row[4]}"
        new_point = geocode(address)
        if new_point:
            row[geometry_idx] = new_point

# zapis z powrotem — dokładnie ta sama struktura
with open(output_file, "w", newline="", encoding="utf-8") as fout:
    writer = csv.writer(fout, delimiter=";")
    writer.writerow(headers)
    writer.writerows(rows)

print("Gotowe. Wynik zapisany w", output_file)
