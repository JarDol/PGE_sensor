# PGE Sensor

Integracja Home Assistant oraz skrypt CLI do pobierania informacji o rozliczeniach i rachunkach z portalu PGE (eBOK).

## Funkcje

- **Integracja Home Assistant** - automatyczne tworzenie sensorów dla stanu konta, terminów płatności oraz parametrów zużycia energii.
- **Wielu punktów poboru** - obsługa wielu PPE na jednym koncie (każdy punkt tworzy osobne urządzenie w HA).
- **Szczegółowe dane** - m.in. energia pobrana, wprowadzona, zbilansowana, magazyn energii, okres rozliczeniowy.
- **Skrypt CLI** - opcjonalny skrypt `pge_scraper.py` dla szybkiej kontroli salda z poziomu konsoli.

## Wymagania

- Aktywne konto w serwisie https://ebok.gkpge.pl.
- Instancja Home Assistant (dla integracji) lub Python 3.10+ (dla skryptu CLI).

## Sensory

Integracja tworzy następujące sensory dla każdego skonfigurowanego Punktu Poboru (PPE):

| Sensor | Opis | Wartość |
|--------|------|---------|
| `sensor.pge_balance` | **PGE Saldo** - kwota pozostała do zapłaty. W atrybutach m.in. data i status płatności, numer faktury. | PLN |
| `sensor.pge_payment_due_date` | **PGE Termin płatności** - data, do której należy opłacić rachunek. | data |
| `sensor.pge_invoice_amount` | **PGE Kwota faktury** - całkowita kwota z najnowszej faktury. | PLN |
| `sensor.pge_biezaca_platnosc` | **PGE Bieżąca płatność** - kwota do zapłaty wyłącznie za najnowszą fakturę. | PLN |
| `sensor.pge_consumed_energy` | **PGE Energia pobrana** - energia pobrana z sieci (w kWh). | kWh |
| `sensor.pge_feed_in_energy` | **PGE Energia wprowadzona** - nadwyżka wyprodukowanej energii wprowadzona do sieci. | kWh |
| `sensor.pge_settled_energy` | **PGE Zużycie po rozliczeniu** - faktyczna ilość energii po zbilansowaniu. | kWh |
| `sensor.pge_magazyn_energii` | **PGE Magazyn energii** - pozostała do rozliczenia energia (historia w atrybutach). | kWh |
| `sensor.pge_okres_rozliczeniowy` | **PGE Okres rozliczeniowy** - przedział dat dla najnowszej faktury. | tekst |

Koordynator aktualizuje dane co 8 godzin, a w przypadku błędu (np. przerwa techniczna eBOK) ponawia próby co 30 minut.

## Instalacja

### Opcja 1: HACS (Zalecana)

Kliknij poniższy przycisk, aby automatycznie dodać repozytorium do HACS:

[![Otwórz w HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=procaktomasz&repository=PGE_sensor&category=integration)

Lub ręcznie:

1. Otwórz HACS w Home Assistant.
2. Kliknij trzy kropki w prawym górnym rogu.
3. Wybierz **Custom repositories**.
4. W polu URL wpisz: `https://github.com/procaktomasz/PGE_sensor`
5. W polu Category wybierz: **Integration**.
6. Kliknij Add, a następnie wyszukaj "PGE Sensor" i zainstaluj komponent.
7. Zrestartuj Home Assistant.

### Opcja 2: Instalacja manualna

1. Skopiuj folder `custom_components/pge_sensor` do folderu `config/custom_components/` w konfiguracji HA.
2. Zrestartuj Home Assistant.

## Konfiguracja

1. Przejdź do: **Konfiguracja** > **Urządzenia i Usługi** > **Dodaj integrację**.
2. Wyszukaj **PGE Sensor**.
3. Podaj swoje dane logowania do serwisu eBOK.
4. Jeśli konto posiada wiele punktów poboru, instalator zapyta, czy chcesz dodać wszystkie naraz, czy tylko wybrany. Aby w przyszłości dodać kolejny, uruchom konfigurację ponownie z tymi samymi danymi.

## Rozwiązywanie problemów

- Jeśli logowanie kończy się błędem, sprawdź czy portal eBOK nie wymaga autoryzacji SMS/e-mail (zaloguj się ręcznie w przeglądarce i zaakceptuj żądanie).
- Zmiany na stronie eBOK mogą powodować tymczasowy brak danych w sensorach. 
- Aby włączyć logowanie dla integracji, dodaj w `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.pge_sensor: debug
```

## Nota prawna

Projekt licencjonowany na zasadach MIT. Jest to projekt prywatny, niepowiązany, niesponsorowany ani niewspierany przez PGE Polska Grupa Energetyczna S.A. Nazwy i znaki towarowe należą do ich właścicieli i służą wyłącznie do celów identyfikacyjnych.
Źródłem danych dla integracji jest https://ebok.gkpge.pl/.
