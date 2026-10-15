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

Integracja tworzy następujące sensory dla każdego skonfigurowanego Punktu Poboru (PPE). Nazwy encji mają postać `sensor.pge_<numer PPE>_<sensor>`, np. `sensor.pge_590243000000000001_saldo` — patrz [Identyfikatory encji](#identyfikatory-encji). Poniższa tabela pokazuje nazwy z wersji sprzed tej zmiany:

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
| `sensor.pge_<PPE>_magazyn_biezacy` | **PGE Magazyn energii — bieżący z licznika** - stan banku energii na dziś, wyliczony z Twoich liczników (tylko gdy podasz liczniki, patrz niżej). | kWh |

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
5. Opcjonalnie wskaż liczniki energii pobranej i oddanej (patrz niżej). Można je dodać lub zmienić później przyciskiem **Konfiguruj** przy integracji.

### Bieżący magazyn energii z licznika

PGE pokazuje bank energii tylko na dzień ostatniego rzeczywistego rozliczenia. Jeśli wskażesz liczniki energii pobranej i oddanej (np. z licznika dwukierunkowego, falownika lub Shelly), integracja doliczy do tego banku Twoje odczyty od dnia po zakończeniu rozliczonego okresu:

- energia oddana w danym miesiącu trafia do banku po przemnożeniu przez współczynnik opustu PGE (np. 0,8),
- pobór zużywa najpierw najstarsze partie energii,
- partie wygasają po 12 miesiącach,
- gdy w banku zabraknie energii, wartość staje się ujemna (energia do zapłaty) i jest spłacana z kolejnych oddań.

Wymagania:

- oba liczniki muszą być narastającymi sensorami energii (`device_class: energy`, `state_class: total_increasing` lub `total`) z historią w statystykach długoterminowych — takie, jakie można wybrać w panelu Energia,
- statystyki muszą sięgać początku bieżącego okresu (dnia po końcu ostatniego rozliczenia); bez tego sensor jest niedostępny, a w logu pojawia się ostrzeżenie,
- obsługiwane są taryfy jednostrefowe (np. G11); przy koncie z bankiem w dwóch strefach sensor pozostaje niedostępny.

W ustawieniach (kreator lub **Konfiguruj**) można też ustawić:

- **Dokładność** (0,01 / 0,1 / 0,5 / 1 kWh, domyślnie 0,1) — krok zaokrąglenia stanu i atrybutów energii. Sensor zmienia wartość dopiero o pełny krok, więc większy krok oznacza rzadsze aktualizacje i mniej wpisów w bazie.
- **Współczynnik opustu** — domyślnie puste: używany jest współczynnik podany przez PGE w ostatnim rozliczeniu, a gdy PGE go nie podało — 0,8. Wpisana wartość (np. 0,7 dla instalacji 10–50 kW) zastępuje oba. Atrybut `factor_zrodlo` pokazuje, skąd pochodzi użyty współczynnik (`PGE`, `ręczny`, `domyślny`), a `factor_pge` — wartość od PGE.

Odczyty z początku każdego miesiąca pobierane są ze statystyk co godzinę, a wartość przeliczana jest przy każdej zmianie stanu licznika. W atrybutach sensora znajdziesz m.in. pobór i oddanie od początku okresu, deficyt, energię, która wygasła, oraz listę partii z datą wygaśnięcia (`partie`, `najblizsze_wygasniecie`).

### Identyfikatory encji

Encje są nazywane według numeru punktu poboru (PPE), a nie numeru konta: `sensor.pge_<PPE>_saldo`, `sensor.pge_<PPE>_magazyn_energii` itd. Numer PPE oznacza fizyczny punkt i nie zmienia się, gdy PGE zmienia numer konta rozliczeniowego. Jeśli konto obejmuje kilka punktów poboru, w nazwie zostaje numer konta.

Przy pierwszym uruchomieniu wersji z tą zmianą istniejące encje są jednorazowo przemianowane na nowy wzorzec. Home Assistant przenosi przy tym historię i statystyki, ale karty i automatyzacje używające starych nazw trzeba poprawić. Późniejsze ręczne zmiany nazw nie są nadpisywane.

### Zmiana konta rozliczeniowego przez PGE

Gdy PGE zarchiwizuje skonfigurowane konto, a ten sam punkt poboru pojawi się na nowym, aktywnym koncie, w **Ustawienia → Naprawy** pojawi się zgłoszenie „PGE zastąpiło konto rozliczeniowe”. Po jego zatwierdzeniu integracja zaczyna pobierać dane z nowego konta, a encje, ich nazwy i cała historia pozostają bez zmian.

- Zanim zatwierdzisz, opłać fakturę końcową starego konta — po przeniesieniu jego saldo nie jest już śledzone.
- Nowe konto może jeszcze nie mieć faktury rozliczeniowej; do tego czasu sensory rozliczenia i banku mogą być niedostępne.
- Jeśli nowe konto zostało już dodane jako osobna integracja, usuń ją przed zatwierdzeniem naprawy.
- Zgłoszenie nie pojawi się, jeśli ten sam punkt jest na kilku aktywnych kontach (nie da się wtedy jednoznacznie wskazać następcy).

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
