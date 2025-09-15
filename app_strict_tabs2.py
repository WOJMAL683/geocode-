import io
import csv
import re
import time
import requests
import pandas as pd
import streamlit as st

try:
    from charset_normalizer import from_bytes as detect_encoding
except Exception:
    detect_encoding = None

# ----------------- Helpers -----------------

def clean(val):
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    return str(val).strip()

def find_lineterminator(raw: bytes) -> str:
    if b"\r\n" in raw:
        return "\r\n"
    elif b"\r" in raw and b"\n" not in raw:
        return "\r"
    else:
        return "\n"

def sniff_dialect(sample_text: str):
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample_text, delimiters=[",",";","\t","|"])
    except Exception:
        class Dialect(csv.Dialect):
            delimiter = ","
            quotechar = '"'
            doublequote = True
            escapechar = None
            skipinitialspace = False
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL
        dialect = Dialect
    return dialect

def normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", clean(h).lower().replace("\u00a0"," ")).replace(" ", "_")

def map_columns(header):
    variants = {
        "gpsposition": {"gpsposition","gps_position","gps position","gps","geom","geometry"},
        "name": {"name","nazwa","poi_name","title"},
        "post_code": {"post_code","post code","postcode","kod","kod_pocztowy","zip","zip_code"},
        "city_name": {"city_name","city name","city","miasto","locality","town"},
        "street_name": {"street_name","street name","street","ulica","road"},
        "house_number": {"house_number","house number","nr","nr_domu","nr domu","numer","housenumber","building_number"},
    }
    idx = {}
    for i,h in enumerate(header):
        key = normalize_header(h)
        for target, names in variants.items():
            if key in names and target not in idx:
                idx[target] = i
    return idx

def detect_gps_format_from_rows(rows, gps_idx):
    for r in rows[1:]:
        if gps_idx >= len(r): 
            continue
        s = clean(r[gps_idx])
        if not s:
            continue
        up = s.upper()
        if up.startswith("POINT"):
            return {"type":"wkt_point"}
        sep = "," if "," in s else (" " if " " in s else ",")
        parts = re.split(r"[,\s]+", s.strip())
        if len(parts) >= 2:
            try:
                a = float(parts[0]); b = float(parts[1])
                if abs(a) <= 90 and abs(b) <= 180:
                    order = "latlon"
                elif abs(b) <= 90 and abs(a) <= 180:
                    order = "lonlat"
                else:
                    order = "latlon"
                return {"type":"plain","order":order,"sep":sep}
            except:
                pass
    return {"type":"plain","order":"latlon","sep":","}

def format_gps(fmt, lat, lon):
    lat_s = str(lat); lon_s = str(lon)
    if fmt.get("type") == "wkt_point":
        return f"POINT ({lon_s} {lat_s})"
    else:
        order = fmt.get("order","latlon"); sep = fmt.get("sep",",")
        if order == "lonlat":
            return f"{lon_s}{sep}{lat_s}"
        else:
            return f"{lat_s}{sep}{lon_s}"

def geocode_nominatim(address, country_code="PL", pause=1.2, user_agent="GeocodeApp/1.0 (kontakt@example.com)"):
    base = "https://nominatim.openstreetmap.org/search"
    params = {"format":"json","q":address,"addressdetails":1,"limit":1}
    if country_code: params["countrycodes"] = country_code.lower()
    headers = {"User-Agent": user_agent}
    try:
        resp = requests.get(base, params=params, headers=headers, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                lat = data[0].get("lat"); lon = data[0].get("lon")
                addr = data[0].get("address", {})
                return lat, lon, addr, None
            return None, None, None, "ZERO_RESULTS"
        else:
            return None, None, None, f"HTTP_{resp.status_code}"
    except Exception as e:
        return None, None, None, f"EXC:{e}"
    finally:
        time.sleep(pause)

def geocode_google(address, api_key):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": api_key}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                return loc["lat"], loc["lng"], None
            else:
                return None, None, data.get("status")
        else:
            return None, None, f"HTTP_{resp.status_code}"
    except Exception as e:
        return None, None, f"EXC:{e}"

def build_address(pc, city, street, house):
    parts = []
    if street and house: parts.append(f"{street} {house}")
    elif street: parts.append(street)
    elif house: parts.append(house)
    if city: parts.append(city)
    if pc: parts.append(pc)
    return ", ".join([p for p in parts if clean(p)])

# ----------------- Streamlit UI -----------------

st.set_page_config(page_title="Geocoding CSV + HTML", page_icon="🌍", layout="wide")

tab1, tab2, tab3 = st.tabs(["🛰️ Geokodowanie", "📄 Wstępny", "📄 Końcowy"])

with tab1:
    st.title("🛰️ Geocoding CSV – STRICT + LIVE")
    st.write("CSV wyjściowy zachowuje **identyczny format** jak wejściowy. "
             "Na żywo pokazuję, czy użyto **OSM**, **GOOGLE**, czy brak wyniku (**!!!**).")

    with st.sidebar:
        st.header("Ustawienia")
        country = st.text_input("Kod kraju (bias)", value="PL")
        pause = st.number_input("Pauza między zapytaniami (sekundy)", min_value=0.0, max_value=5.0, value=1.2, step=0.1)
        only_empty = st.checkbox("Aktualizuj tylko puste gpsposition", value=False)
        user_agent = st.text_input("User-Agent", value="GeocodeApp/1.0 (kontakt@example.com)")
        google_api_key = st.text_input("Google API Key (opcjonalnie)", type="password")

    uploaded = st.file_uploader("📤 Wgraj plik CSV", type=["csv"])

    if uploaded is not None:
        raw = uploaded.read()
        had_bom = raw.startswith(b"\xef\xbb\xbf")
        encoding = "utf-8"
        if detect_encoding is not None:
            enc_res = detect_encoding(raw).best()
            if enc_res and enc_res.encoding:
                encoding = enc_res.encoding
        sample_text = raw[:4096].decode(encoding, errors="replace")
        dialect = sniff_dialect(sample_text)
        lineterm = find_lineterminator(raw)
        text_io = io.TextIOWrapper(io.BytesIO(raw), encoding=encoding, newline="")
        reader = csv.reader(text_io, dialect)
        rows = [row for row in reader]
        if not rows:
            st.error("Plik jest pusty.")
            st.stop()
        header = rows[0]
        idx_map = map_columns(header)
        required = ["gpsposition","name","post_code","city_name","street_name","house_number"]
        missing = [c for c in required if c not in idx_map]
        if missing:
            st.error("Brakuje wymaganych kolumn: " + ", ".join(missing))
            st.info("Znalezione nagłówki: " + ", ".join(header))
            st.stop()
        gps_idx = idx_map["gpsposition"]
        name_idx = idx_map["name"]
        fmt = detect_gps_format_from_rows(rows, gps_idx)

        st.subheader("Podgląd (pierwsze 10 wierszy – bez zmian):")
        st.table(pd.DataFrame(rows[:11]))

        log_placeholder = st.empty()
        progress = st.progress(0)

        if st.button("🚀 Start geokodowania (STRICT + LIVE)"):
            updated = 0
            flagged = 0
            cnt_osm = 0
            cnt_google = 0

            logs = []

            total = max(1, len(rows)-1)
            for i in range(1, len(rows)):
                r = rows[i]
                while len(r) < len(header):
                    r.append("")

                pc = clean(r[idx_map["post_code"]])
                city = clean(r[idx_map["city_name"]])
                street = clean(r[idx_map["street_name"]])
                house = clean(r[idx_map["house_number"]])
                gps_current = clean(r[gps_idx])

                if only_empty and gps_current:
                    progress.progress(i/total)
                    continue

                if not house or not city:
                    r[name_idx] = "!!!"
                    flagged += 1
                    logs.append(f"[{i}/{total}] {build_address(pc, city, street, house)} → !!! brak")
                    log_placeholder.code("\n".join(logs[-30:]))
                    progress.progress(i/total)
                    continue

                address = build_address(pc, city, street, house)

                lat, lon, addr, err = geocode_nominatim(address, country_code=country, pause=pause, user_agent=user_agent)

                used = None
                precise = False
                if lat is not None and lon is not None:
                    if addr and addr.get("house_number"):
                        precise = True
                        used = "OSM"

                if not precise:
                    if google_api_key:
                        lat, lon, gerr = geocode_google(address, google_api_key)
                        if lat is not None and lon is not None:
                            used = "GOOGLE"
                        else:
                            used = None
                    else:
                        used = None

                if lat is None or lon is None or used is None:
                    r[name_idx] = "!!!"
                    flagged += 1
                    logs.append(f"[{i}/{total}] {address} → !!! brak")
                else:
                    r[gps_idx] = format_gps(fmt, lat, lon)
                    updated += 1
                    if used == "OSM":
                        cnt_osm += 1
                    elif used == "GOOGLE":
                        cnt_google += 1
                    logs.append(f"[{i}/{total}] {address} → {used}")

                log_placeholder.code("\n".join(logs[-30:]))
                progress.progress(i/total)

            st.success(f"✅ Zakończono. OSM: {cnt_osm}, GOOGLE: {cnt_google}, Brak: {flagged}")

            out_text = io.StringIO()
            writer = csv.writer(out_text,
                                delimiter=dialect.delimiter,
                                quotechar=getattr(dialect,"quotechar",'"'),
                                escapechar=getattr(dialect,"escapechar",None),
                                doublequote=getattr(dialect,"doublequote",True),
                                quoting=getattr(dialect,"quoting",csv.QUOTE_MINIMAL),
                                lineterminator=lineterm,
                                skipinitialspace=getattr(dialect,"skipinitialspace",False))
            for row in rows:
                writer.writerow(row)
            out_str = out_text.getvalue()
            out_bytes = out_str.encode(encoding, errors="replace")
            if had_bom and encoding.lower().replace("-","") in {"utf8","utf8sig"}:
                out_bytes = b"\xef\xbb\xbf" + out_bytes if not out_bytes.startswith(b"\xef\xbb\xbf") else out_bytes

            st.download_button("⬇️ Pobierz wynik.csv (format 1:1)",
                               data=out_bytes,
                               file_name="wynik.csv",
                               mime="text/csv")

with tab2:
    st.title("📄 Podgląd HTML – Wstępny")
    try:
        with open("plik1.html", "r", encoding="utf-8") as f:
            html = f.read()
        st.components.v1.html(html, height=800, scrolling=True)
    except FileNotFoundError:
        st.warning("❌ Nie znaleziono pliku plik1.html w folderze aplikacji.")

with tab3:
    st.title("📄 Podgląd HTML – Końcowy")
    try:
        with open("plik2.html", "r", encoding="utf-8") as f:
            html = f.read()
        st.components.v1.html(html, height=800, scrolling=True)
    except FileNotFoundError:
        st.warning("❌ Nie znaleziono pliku plik2.html w folderze aplikacji.")
