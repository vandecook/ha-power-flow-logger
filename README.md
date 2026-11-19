# ha-power-flow-logger (AppDaemon-App für Home Assistant)

Status: Entwurf, Logik mit simulierten Werten getestet, **noch nicht in AppDaemon/HA gelaufen**.

## Zweck
Rein **lesendes** Loggen der Leistungsflüsse im Haus, als Grundlage für eine spätere dynamische Leistungsregelung der PV-Wechselrichter. Die App schreibt nichts in Home Assistant, an die OpenDTU oder an Wechselrichter.

Fragen, die der Log beantworten soll:
- Wie hoch sind Hausverbrauch und Netzbezug im Sekundenraster, und wann treten Spitzen auf (Herd, Wärmepumpe, Klimaanlage)?
- Wie schnell liefern die einzelnen Quellen ihre Werte (Alter der Werte in Sekunden)?
- Wie weit weichen die Netz-Messung am Hausanschluss und der AMIS-Zähler voneinander ab?
- Wie verhalten sich die Wechselrichter und Speicher (SOC, Leistung)?
- Später: Viertelstunden-Mittel des Bezugs und Monatsmaximum (Power Shaving), Totzeit der Hoymiles bei Limit-Änderungen.

## Konfiguration (`apps.yaml`)

| Schlüssel | Bedeutung |
|---|---|
| `interval` | Sekunden zwischen den Zeilen (Standard 1). |
| `log_dir` | Zielordner der CSV-Dateien (Standard `/config/appdaemon/lastlog`), eine Datei pro Tag. |
| `grids` | Netzquellen, beliebig viele. Je Quelle **entweder** `entity` (ein vorzeichenbehafteter Sensor, optional `invert: true`) **oder** `in` und `out` (zwei vorzeichenlose Sensoren, je ≥ 0). |
| `primary_grid` | Netzquelle, aus der der Hausverbrauch berechnet wird (Standard: erste). |
| `inverters` | Erzeuger (AC-Leistung in W, Abgabe positiv). Zählen in den Hausverbrauch. |
| `others` | Sonstige Werte, nur Log (WP, Klima, SOC, WR-Limit). |

Quellen unter `inverters`/`others` sind entweder nur die Entität oder ein Block mit:
- `entity`: Sensor.
- `optional: true`: fehlender oder `unavailable` Wert zählt als 0 W.
- `enabled: input_boolean.…`: Steht der Schalter auf `off`, zählt die Quelle als 0 W. Ein Schalter macht die Quelle automatisch optional.

Die Netzquellen (`grids`) sind nicht abschaltbar. Änderungen an `apps.yaml` lädt AppDaemon automatisch neu. Konfigurationsfehler brechen den Start mit einer Meldung im AppDaemon-Log ab.

## Vorzeichen und Formeln
- Netzleistung: **Bezug positiv, Einspeisung negativ**.
  - Ein vorzeichenbehafteter Sensor: Wert direkt (mit `invert: true` umgedreht).
  - Zwei vorzeichenlose Sensoren: `Netz = in − out`.
  - Fehlt ein benötigter Wert, bleibt die Zelle leer (nichts wird geschätzt).
- Hausverbrauch: `Verbrauch = Netz (primär) + Σ Erzeuger`. Nur gültig, wenn alle Erzeugerwerte vorliegen (oder als 0 W zählen).
- Differenz: `Netz(primär) − Netz(andere Quelle)` je weitere Netzquelle.

## CSV-Ausgabe
Eine Datei pro Tag: `lastlog_JJJJ-MM-TT.csv`. Spalten:
1. `ts`: Zeitstempel (lokal, ISO, Sekunden).
2. Rohwerte aller Sensoren, Spaltenname = Name aus `apps.yaml` (bei Paaren `<name>_in` und `<name>_out`).
3. `<name>_age_s`: Alter des Werts in Sekunden seit `last_updated`.
4. `netz_<name>_w`: berechnete Netzleistung je Quelle.
5. `verbrauch_w`: berechneter Hausverbrauch.
6. `diff_<primär>_minus_<name>_w`: Differenz zu jeder weiteren Netzquelle.

Leere Zelle = Wert nicht verfügbar.

## Installation
1. Backup von HA und AppDaemon-Konfiguration.
2. AppDaemon-Add-on installieren bzw. prüfen (Zugriff auf HA, Schreibrecht auf `log_dir`).
3. `last_log.py` und `apps.yaml` in das `apps`-Verzeichnis von AppDaemon legen, Entitäten anpassen.
4. Im AppDaemon-Log prüfen, dass die App startet und die erste CSV entsteht.
5. Ein paar Tage loggen, danach auswerten.

## Geplante Erweiterungen
- Viertelstunden-Mittel des Bezugs (an der Uhr ausgerichtet) und laufendes Monatsmaximum.
- SOC und Leistung der Speichertürme als Spalten.
- WR-Limit mitloggen und einen definierten Limit-Sprung testen, um die Totzeit zu messen.
- Entitäten-Auswahl per HA-Label statt YAML.

## Sicherheit und Datenschutz
- Die App ist rein lesend.
- Keine Logdaten (CSV) und keine Zugangsdaten ins Repo (siehe `.gitignore`).
