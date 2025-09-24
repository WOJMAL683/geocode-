# Geokodowanie CSV

Ten prosty program w Pythonie wykorzystuje API Nominatim (OpenStreetMap), aby dodać lub zaktualizować współrzędne w pliku CSV.

## Jak działa
- Wczytuje plik `wejscie.csv` (separator `;`).
- Znajduje kolumnę `geometry` i podmienia jej wartość na wynik geokodowania.
- Zapisuje wynik w `wyjscie.csv` — plik ma dokładnie tę samą strukturę co wejściowy.

## Użycie

1. Umieść swój plik CSV w katalogu i nazwij go `wejscie.csv`.
2. Uruchom:

```bash
python geokodowanie_fixed.py
```

3. Wynik znajdziesz w pliku `wyjscie.csv`.

## Wymagania

- Python 3.7+
- Zależności z pliku `requirements.txt`

Instalacja:

```bash
pip install -r requirements.txt
```

## API

Program używa [Nominatim OpenStreetMap](https://nominatim.openstreetmap.org/).
