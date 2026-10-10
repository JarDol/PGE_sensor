# Dokumenty płatności, prognozy i rzeczywiste rozliczenie

Integracja odświeża dane z eBOK. Dane energetyczne pochodzą z faktur, więc opisują **ostatni udostępniony okres rozliczeniowy**, a nie bieżący przepływ mocy lub stan licznika. Płatność, prognoza i rzeczywiste rozliczenie mogą pochodzić z różnych dokumentów.

## Istniejące sensory

| Sensor | Zachowanie po zmianie |
| --- | --- |
| Saldo, kwota dokumentu płatności, bieżąca płatność, termin płatności | Zachowują dotychczasowy wybór dokumentu i znaczenie. |
| Energia pobrana / wprowadzona | Pochodzi z ostatniego dokumentu `INVOICE` z danymi energii, wybranego według końca okresu. Dokument `PREPAYMENT_INVOICE` nie zastępuje pomiaru prognozą. |
| Okres rozliczeniowy | Opisuje ten sam rzeczywisty okres co sensory energii. |
| Magazyn energii | Suma dostępnej energii ze stref S1/S2 po zastosowaniu współczynnika PGE, zamiast surowego salda tylko pierwszej strefy. Atrybuty zawierają również surowe salda i współczynniki. |
| Zużycie po rozliczeniu | Wycofane: `valueSettledEnergyConsumed` było błędnie wystawiane jako kWh. Istniejący wpis zostaje wyłączony przez integrację; jego identyfikator i historia nie są usuwane. Kwota otrzymuje nowy sensor PLN. |

Zmiany źródła energii i interpretacji banku są świadomymi naprawami znaczenia danych. Nie są wyłącznie dodatkowymi sensorami. Unique ID pozostałych istniejących sensorów nie zmieniają się.

## Nowe sensory

Sufiks oznacza końcówkę stable unique ID, nie gwarantowaną nazwę `entity_id` w rejestrze HA.

| Sensor / sufiks unique ID | Jednostka | Źródło i znaczenie |
| --- | --- | --- |
| Kwota rzeczywistej faktury rozliczeniowej / `actual_invoice_amount` | PLN | `totalAmount` najnowszego `INVOICE`, również bez danych energii. Ma własne atrybuty numeru i daty faktury. |
| Wartość rozliczenia energii / `settlement_value_pln` | PLN | Pole PGE `valueSettledEnergyConsumed` z rzeczywistego rozliczenia. Nie jest końcową kwotą faktury ani pełnym kosztem prądu. |
| Prognozowany pobór / `forecast_energy` | kWh | `consumptionValue` z najnowszego dokumentu płatności, jeżeli jest `PREPAYMENT_INVOICE`. Atrybut `forecast` odróżnia go od pomiaru. |
| Data salda banku / `bank_date` | data | Koniec okresu faktury, dla której pobrano poprawny bank; przy braku banku data jest niedostępna. |
| Bank S1 / `energy_storage_1` | kWh | Surowe pozostałe saldo S1 × współczynnik tej strefy. |
| Bank S2 / `energy_storage_2` | kWh | Surowe pozostałe saldo S2 × współczynnik tej strefy. |

Najnowsza faktura finansowa może nie zawierać energii. Wtedy kwota tej faktury jest nadal dostępna, a energia może pochodzić z wcześniejszego rozliczenia z kompletnymi danymi. Atrybuty rozróżniają źródła.

## Bank po opuście

W danych PGE `leftEnergyAmountSum` jest saldem surowym. Dostępna energia wynosi to saldo pomnożone przez `factor` ze strefy. Na przykład 100 kWh × 0,8 = 80 kWh. Współczynnik pochodzi z API; nie zakładamy dla wszystkich instalacji 0,8. Alias `Strefa 1 w sumie` nie jest doliczany drugi raz do `Strefa 1`; jest używany wyłącznie jako fallback.

Zero jest poprawnym saldem. Brak salda, brak współczynnika, nieprawidłowe liczby lub niekompletna strefa oznaczają brak pewnego wyniku, a nie zero. Suma banku nie jest publikowana, jeśli brakuje składnika którejś ze stref udostępnionych przez PGE.

To saldo **na datę faktury**, nie wirtualny akumulator aktualizowany na podstawie domowych pomiarów. Integracja nie wylicza bieżącego banku, dat wygaśnięcia każdej partii, taryf ani rzeczywistego kosztu po opuście.

## Zwykły odbiorca i brak danych

Jeśli PGE jawnie zwraca `prosument: false`, sensory oddania i banku są domyślnie wyłączone. Istniejące odpowiednie encje są wyłączane bez usuwania ich wpisów. Wyłączenie użytkownika jest zachowane; integracja przywraca wyłącznie encje wcześniej wyłączone przez siebie, gdy PGE potwierdzi status prosumenta. Brak flagi nie oznacza automatycznie zwykłego odbiorcy.

Zwykłe mieszkanie może mieć kompletny `ppmConsumptions` albo pustą listę. Przy pustej liście saldo, kwoty i termin płatności nadal działają, ale pobór, okres i składnik rozliczenia energii są niedostępne. Brak `PREPAYMENT_INVOICE` oznacza brak prognozy. Nie odtwarzamy zużycia przez dzielenie kwoty faktury przez cenę kWh. Pole wartości energii równe zero nie oznacza bezpłatnej energii — pokazuje wartość przekazaną w tym polu API.

Jeżeli dokument zawiera kilka PPE, sensory pojedynczego okresu/energii/banku nie wybierają arbitralnie pierwszego punktu. Wartość finansowa faktury nadal działa; agregacja lub wybór PPE wymagają osobnego rozwiązania.

## Statystyki i kompatybilność

Energia z pojedynczej faktury, prognoza i saldo banku nie są licznikami kumulacyjnymi. Nie mają `state_class`; nie należy ich wpisywać jako import/eksport w panelu Energia. Do tego potrzebny jest rzeczywisty licznik energii. Usunięcie błędnej klasy zapobiega dodawaniu kolejnych kwot z faktur jako przyrostów licznika.

Dotychczasowe atrybuty banku `settled_energy_sum_with_factor`, `settled_energy_sum`, `factor` i `history` są zachowane. Dodatkowo dostępne są szczegóły stref oraz dane identyfikujące rozliczenie. Częstotliwość odświeżania i logowanie nie zmieniają się. Lista dokumentów ma zwiększony limit z 15 do 100, aby znaleźć fakturę rzeczywistą wśród nowszych prognoz. Odczyt jest ograniczony do tych dokumentów; nie dodano pełnej paginacji.

Zmiana nie usuwa ani nie przelicza istniejących statystyk, które zostały wcześniej zapisane z błędnym znaczeniem jednostki lub licznika.

## Testy

```sh
python3 -m unittest discover -s tests -p 'test_pge_settlement*.py' -v
```

Testy korzystają z fikcyjnych dokumentów i małych atrap interfejsów HA/HTTP. Nie wymagają połączenia z PGE ani danych logowania. Sprawdzają parser API, wybór dokumentu, jednostki i wartości sensorów, dostępność, wyłączanie nieobsługiwanych możliwości i obliczenia banku. Nie zastępują testu rejestracji na pełnej instancji HA.
