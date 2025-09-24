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

with open(input_file, "r", encoding="utf-8") as f:
    lines = f.read().splitlines()

header = lines[0]
columns = header.split(";")
geometry_idx = columns.index("geometry")

output_lines = [header]

for line in lines[1:]:
    if not line.strip():
        output_lines.append(line)
        continue

    parts = line.split(";")

    # przykładowy adres: street_name (2), house_number (3), city_name (4)
    address = f"{parts[2]} {parts[3]}, {parts[4]}"
    new_point = geocode(address)

    if new_point:
        parts[geometry_idx] = new_point

    # zachowujemy dokładnie ten sam format CSV
    output_lines.append(";".join(parts))

with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines))

print("Gotowe. Wynik zapisany w", output_file)
