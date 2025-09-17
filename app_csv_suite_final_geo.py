import io, csv, re, time, json, os
import requests, pandas as pd, streamlit as st
from charset_normalizer import from_bytes as detect_encoding

# ----------------- Helpers -----------------
def clean(val):
    return str(val).strip() if val else ""

def find_lineterminator(raw: bytes) -> str:
    if b"\r\n" in raw: return "\r\n"
    elif b"\r" in raw and b"\n" not in raw: return "\r"
    else: return "\n"

def sniff_dialect(sample_text: str):
    sniffer = csv.Sniffer()
    try:
        return sniffer.sniff(sample_text, delimiters=[",",";","\t","|"])
    except:
        class Dialect(csv.Dialect):
            delimiter = ","; quotechar = '"'; doublequote = True
            escapechar = None; skipinitialspace = False; lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL
        return Dialect

def normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", clean(h).lower()).replace(" ", "_")

def map_columns(header):
    variants = {
        "gpsposition": {"gpsposition","gps_position","gps position","gps"},
        "name": {"name","nazwa"},
        "edit_name": {"edit_name","edit name","edit"},
        "post_code": {"post_code","postcode","zip","kod"},
        "city_name": {"city","city_name","miasto"},
        "street_name": {"street","street_name","ulica"},
        "house_number": {"house","house_number","nr","numer"}
    }
    idx = {}
    for i,h in enumerate(header):
        key = normalize_header(h)
        for target,names in variants.items():
            if key in names and target not in idx:
                idx[target]=i
    return idx

# ----------------- Cleaning -----------------
STACJA_PATTERN = re.compile(r"stacj[ai] paliw", re.IGNORECASE)
KEYWORDS_KEEP = ["kebab","pizza","burger","lody","pub","kawiarnia"]
SMALL_WORDS = {"i","w","z","do","na","od","u","o","po","za","pod","nad","przy","al.","ul."}

def title_case_pl(text: str):
    words = text.split(); out=[]
    for i,w in enumerate(words):
        lw=w.lower()
        if i>0 and lw in SMALL_WORDS: out.append(lw)
        else: out.append(lw.capitalize())
    return " ".join(out)

def clean_name_auto(name: str, remove_list) -> str:
    s=str(name or "").strip()
    if STACJA_PATTERN.search(s):
        brand=None
        for p in s.split():
            if p.lower() in ["orlen","lotos","shell","bp"]: brand=p
        return f"Punkt gastronomiczny {brand}" if brand else "Punkt gastronomiczny"
    for phrase in remove_list:
        s = re.sub(re.escape(phrase), " ", s, flags=re.IGNORECASE)
    if any(kw in s.lower() for kw in KEYWORDS_KEEP):
        s = re.sub(r"(?i)punkt|zakład", " ", s)
    s = re.sub(r"\s+"," ",s).strip(" .,-_/\\;:()[]{}")
    return title_case_pl(s)

# ----------------- Load/save rules -----------------
RULES_FILE="custom_rules.json"
def load_rules():
    if os.path.exists(RULES_FILE):
        with open(RULES_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    return []
def save_rules(rules):
    with open(RULES_FILE,"w",encoding="utf-8") as f:
        json.dump(rules,f,ensure_ascii=False,indent=2)

# ----------------- Geocoding -----------------
def geocode_nominatim(address, country_code="PL", pause=1.2, user_agent="GeocodeApp/1.0"):
    url="https://nominatim.openstreetmap.org/search"
    params={"format":"json","q":address,"addressdetails":1,"limit":1,"countrycodes":country_code.lower()}
    try:
        r=requests.get(url,params=params,headers={"User-Agent":user_agent},timeout=12)
        if r.status_code==200:
            data=r.json()
            if data: return data[0]["lat"],data[0]["lon"],data[0].get("address",{}),None
            else: return None,None,None,"ZERO_RESULTS"
        return None,None,None,f"HTTP_{r.status_code}"
    except Exception as e:
        return None,None,None,str(e)
    finally: time.sleep(pause)

def geocode_google(address, api_key):
    url="https://maps.googleapis.com/maps/api/geocode/json"
    try:
        r=requests.get(url,params={"address":address,"key":api_key},timeout=10)
        if r.status_code==200:
            data=r.json()
            if data.get("status")=="OK" and data["results"]:
                loc=data["results"][0]["geometry"]["location"]
                return loc["lat"],loc["lng"],None
            else: return None,None,data.get("status")
        return None,None,f"HTTP_{r.status_code}"
    except Exception as e: return None,None,str(e)

def build_address(pc,city,street,house):
    parts=[]
    if street and house: parts.append(f"{street} {house}")
    elif street: parts.append(street)
    elif house: parts.append(house)
    if city: parts.append(city)
    if pc: parts.append(pc)
    return ", ".join([p for p in parts if p])

def format_gps(lat,lon): return f"{lat},{lon}"

# ----------------- UI -----------------
st.set_page_config(page_title="Obróbka CSV", page_icon="🧭", layout="wide")
st.markdown("<h1 style='text-align: center; font-size: 42px;'>OBRÓBKA CSV</h1>", unsafe_allow_html=True)
tab1,tab2,tab3,tab4=st.tabs(["🛰️ Geokodowanie","📄 Wstępny","📄 Końcowy","🧹 Nazwy"])

# Tab1 Geocoding
with tab1:
    st.header("🛰️ Geocoding CSV – STRICT + LIVE")
    with st.expander("⚙️ Ustawienia",expanded=True):
        country=st.text_input("Kod kraju",value="PL")
        pause=st.number_input("Pauza (s)",0.0,5.0,1.2,0.1)
        only_empty=st.checkbox("Aktualizuj tylko puste gpsposition",value=False)
        user_agent=st.text_input("User-Agent",value="GeocodeApp/1.0")
        google_api_key=st.text_input("Google API Key (opcjonalnie)",type="password")
    uploaded=st.file_uploader("📤 Wgraj plik CSV (Geokodowanie)",type=["csv"],key="geo_csv")
    if uploaded:
        raw=uploaded.read()
        enc="utf-8"; enc_res=detect_encoding(raw).best()
        if enc_res and enc_res.encoding: enc=enc_res.encoding
        sample=raw[:4096].decode(enc,errors="replace")
        dialect=sniff_dialect(sample)
        lineterm=find_lineterminator(raw)
        text_io=io.TextIOWrapper(io.BytesIO(raw),encoding=enc,newline="")
        reader=csv.reader(text_io,dialect)
        rows=[r for r in reader]
        if not rows: st.error("Plik pusty"); st.stop()
        header=rows[0]; idx=map_columns(header)
        if "gpsposition" not in idx: st.error("Brak gpsposition"); st.stop()
        gps_idx=idx["gpsposition"]; name_idx=idx.get("name")
        st.table(pd.DataFrame(rows[:11]))
        log_placeholder=st.empty(); progress=st.progress(0)
        if st.button("🚀 Start geokodowania"):
            logs=[]; updated=flagged=cnt_osm=cnt_google=0; total=max(1,len(rows)-1)
            for i in range(1,len(rows)):
                r=rows[i]; pc=r[idx.get("post_code","")] if "post_code" in idx else ""
                city=r[idx.get("city_name","")] if "city_name" in idx else ""
                street=r[idx.get("street_name","")] if "street_name" in idx else ""
                house=r[idx.get("house_number","")] if "house_number" in idx else ""
                gps=r[gps_idx]
                if only_empty and gps: progress.progress(i/total); continue
                if not house or not city:
                    if name_idx is not None: r[name_idx]="!!!"; flagged+=1
                    logs.append(f"[{i}/{total}] brak danych → !!!")
                    log_placeholder.code("\n".join(logs[-30:])); progress.progress(i/total); continue
                addr=build_address(pc,city,street,house)
                lat,lon,addr_osm,err=geocode_nominatim(addr,country,pause,user_agent)
                used=None
                if lat and lon and addr_osm and addr_osm.get("house_number"): used="OSM"
                if not used and google_api_key:
                    lat,lon,gerr=geocode_google(addr,google_api_key)
                    if lat and lon: used="GOOGLE"
                if not used:
                    if name_idx is not None: r[name_idx]="!!!"; flagged+=1
                    logs.append(f"[{i}/{total}] {addr} → brak")
                else:
                    r[gps_idx]=format_gps(lat,lon); updated+=1
                    if used=="OSM": cnt_osm+=1
                    else: cnt_google+=1
                    logs.append(f"[{i}/{total}] {addr} → {used}")
                log_placeholder.code("\n".join(logs[-30:])); progress.progress(i/total)
            st.success(f"OSM: {cnt_osm}, GOOGLE: {cnt_google}, Brak: {flagged}")
            out_text=io.StringIO(); writer=csv.writer(out_text,delimiter=dialect.delimiter,
                quotechar=getattr(dialect,"quotechar",'"'),doublequote=True,
                lineterminator=lineterm,quoting=csv.QUOTE_MINIMAL)
            for row in rows: writer.writerow(row)
            out_bytes=out_text.getvalue().encode(enc,errors="replace")
            st.download_button("⬇️ Pobierz wynik.csv",data=out_bytes,file_name="wynik.csv",mime="text/csv")

# Tab2 HTML1
with tab2:
    st.header("📄 Wstępny")
    try:
        with open("plik1.html","r",encoding="utf-8") as f: html=f.read()
        st.components.v1.html(html,height=800,scrolling=True)
    except: st.warning("❌ Brak pliku plik1.html")

# Tab3 HTML2
with tab3:
    st.header("📄 Końcowy")
    try:
        with open("plik2.html","r",encoding="utf-8") as f: html=f.read()
        st.components.v1.html(html,height=800,scrolling=True)
    except: st.warning("❌ Brak pliku plik2.html")

# Tab4 Names
with tab4:
    st.header("🧹 Automatyczne czyszczenie nazw (kolumna edit_name)")
    st.subheader("⚙️ Reguły czyszczenia")
    rules=load_rules(); new_rule=st.text_input("Dodaj frazę:")
    if st.button("➕ Dodaj frazę"):
        if new_rule and new_rule not in rules:
            rules.append(new_rule); save_rules(rules); st.success(f"Dodano: {new_rule}")
    if rules: st.write("Frazy:",rules)
    uploaded=st.file_uploader("📤 Wgraj CSV (Nazwy)",type=["csv"],key="names_csv")
    if uploaded:
        raw=uploaded.read(); enc="utf-8"; enc_res=detect_encoding(raw).best()
        if enc_res and enc_res.encoding: enc=enc_res.encoding
        sample=raw[:4096].decode(enc,errors="replace")
        dialect=sniff_dialect(sample); lineterm=find_lineterminator(raw)
        text_io=io.TextIOWrapper(io.BytesIO(raw),encoding=enc,newline="")
        reader=csv.reader(text_io,dialect); rows=[r for r in reader]
        if not rows: st.error("Plik pusty"); st.stop()
        header=rows[0]; idx=map_columns(header)
        if "edit_name" not in idx: st.error("Brak kolumny edit_name"); st.stop()
        edit_idx=idx["edit_name"]
        preview=[{"Before":r[edit_idx],"After":clean_name_auto(r[edit_idx],rules)} for r in rows[1:21]]
        st.table(pd.DataFrame(preview))
        if st.button("🧹 Start czyszczenia"):
            changed=0
            for i in range(1,len(rows)):
                before=rows[i][edit_idx]; after=clean_name_auto(before,rules)
                if after!=before: rows[i][edit_idx]=after; changed+=1
            st.success(f"Zmienione wiersze: {changed}")
            out_text=io.StringIO(); writer=csv.writer(out_text,delimiter=dialect.delimiter,
                quotechar=getattr(dialect,"quotechar",'"'),doublequote=True,
                lineterminator=lineterm,quoting=csv.QUOTE_MINIMAL)
            for row in rows: writer.writerow(row)
            out_bytes=out_text.getvalue().encode(enc,errors="replace")
            st.download_button("⬇️ Pobierz wynik.csv",data=out_bytes,file_name="wynik.csv",mime="text/csv")
