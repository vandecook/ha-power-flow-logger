# HA Power Flow Logger (AppDaemon-App für Home Assistant)

Status: Entwurf, Logik mit simulierten Werten getestet, **noch nicht in AppDaemon/HA gelaufen**.

## Zweck
Rein **lesendes** Loggen der Leistungsflüsse im Haus, als Grundlage für eine spätere dynamische Leistungsregelung der PV-Wechselrichter. Die App schreibt nichts in Home Assistant, an die OpenDTU oder an Wechselrichter.

Fragen, die der Log beantworten soll:
- Wie hoch sind Hausverbrauch und Netzbezug im Sekundenraster, und wann treten Spitzen auf (Herd, Wärmepumpe, Klimaanlage)?
- Wie schnell liefern die einzelnen Quellen ihre Werte (Alter der Werte in Sekunden)?
- Wie weit weichen die Netz-Messung am Hausanschluss und der AMIS-Zähler voneinander ab?
- Wie verhalten sich die Wechselrichter und Speicher (SOC, Leistung)?
- Später: Viertelstunden-Mittel des Bezugs und Monatsmaximum (Power Shaving), Totzeit der Hoymiles bei Limit-Änderungen.

## Konfiguration (`apps.yaml`, Vorlage: `apps/power_flow_logger/apps.yaml.example`)

| Schlüssel | Bedeutung |
|---|---|
| `interval` | Sekunden zwischen den Zeilen (Standard 1). |
| `log_dir` | Zielordner der CSV-Dateien (Standard `/config/lastlog`), eine Datei pro Tag. |
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

## Voraussetzungen
- **Home Assistant** mit installierter AppDaemon-App ("AppDaemon" der Home Assistant Community Apps, früher Add-on; getestet mit AppDaemon 0.19.3 / 4.5, Home Assistant 2026.11). Unter Home Assistant OS oder Supervised: Einstellungen, Apps, Store, "AppDaemon", Installieren, Start beim Booten aktivieren und starten. Bei anderen Installationsarten (Docker, venv) AppDaemon 4.x mit HASS-Plugin und Long-Lived Token einrichten.
- **Sensoren in Home Assistant**, die Leistung in **W** liefern (nicht kW):
  - mindestens eine Netzquelle: entweder ein vorzeichenbehafteter Sensor (z. B. Shelly 3EM total power) oder zwei vorzeichenlose Sensoren für Bezug und Einspeisung (z. B. AMIS-Leser). Mehrere Netzquellen sind möglich und werden verglichen.
  - optional die AC-Leistung der Wechselrichter (z. B. OpenDTU-Sensoren) und weitere Werte wie Wärmepumpe oder SOC.
- **Schreibrecht** im Log-Ordner. In der AppDaemon-App ist `/config` der Konfigurationsordner der App (im SSH-Terminal `/addon_configs/<id>_appdaemon/`, ab 2026.11 auch `/app_configs/<id>_appdaemon/`). `log_dir: /config/lastlog` landet dort.
- **Speicherplatz:** eine Zeile pro Sekunde ergibt je nach Sensorzahl grob 10 bis 20 MB pro Tag. Bei Dauerbetrieb `interval` erhöhen oder alte Dateien regelmäßig löschen.
- Ein **Backup** von Home Assistant vor der Installation.

## Installation
Der Marketplace von Home Assistant (ab 2026.11) und HACS installieren **keine AppDaemon-Apps**. Die Installation erfolgt deshalb von Hand.

1. **AppDaemon starten** (siehe Voraussetzungen). Im Protokoll muss `Connected to Home Assistant` und `Using /config/apps as app_dir` stehen.
2. **App-Ordner anlegen:** im Konfigurationsordner der AppDaemon-App (SSH, Datei-Editor oder Samba) den Ordner `apps/power_flow_logger/` anlegen.
3. **Code herunterladen und kopieren.** `<id>` ist der Ordner der AppDaemon-App, z. B. `a0d7b954_appdaemon`. Bei älteren Installationen heißt der Oberordner `/addon_configs/` statt `/app_configs/`. Eine der drei Möglichkeiten:

   **a) Mit Git (SSH-Terminal):**
   ```
   mkdir -p /app_configs/<id>/apps/power_flow_logger
   git clone https://github.com/vandecook/ha-power-flow-logger /tmp/ha-power-flow-logger
   cp /tmp/ha-power-flow-logger/apps/power_flow_logger/power_flow_logger.py /app_configs/<id>/apps/power_flow_logger/
   ```

   **b) Nur die eine Datei per curl oder wget (kein Git nötig):**
   ```
   mkdir -p /app_configs/<id>/apps/power_flow_logger
   curl -fL -o /app_configs/<id>/apps/power_flow_logger/power_flow_logger.py \
     https://raw.githubusercontent.com/vandecook/ha-power-flow-logger/main/apps/power_flow_logger/power_flow_logger.py
   ```
   (oder `wget -O <Zieldatei> <URL>`). Für einen festen Stand `main` in der URL durch einen Tag wie `v0.1` ersetzen.

   **c) Von Hand:** Datei im Browser öffnen, "Raw" wählen, den Inhalt kopieren und im Datei-Editor von Home Assistant in `apps/power_flow_logger/power_flow_logger.py` einfügen.

4. **Konfiguration eintragen:** den Block aus `apps.yaml.example` ans Ende von `apps/apps.yaml` (im AppDaemon-Konfigurationsordner) hängen und alle Entitäten anpassen. Bestehende Apps bleiben unberührt.
5. **Vorzeichen prüfen:** bei einem vorzeichenbehafteten Netzsensor muss Bezug positiv sein, sonst `invert: true` setzen. Test: nachts ohne PV einen Verbraucher einschalten, `netz_<name>_w` muss steigen.
6. **Log prüfen:** AppDaemon lädt die `apps.yaml` selbst neu. Im Protokoll erscheint `Belastungslog gestartet (…)`, danach liegt die erste CSV in `log_dir`. Fehler (Tippfehler bei Modul, Klasse oder Entität) stehen ebenfalls dort.

**Updates:** Die Datei `power_flow_logger.py` ersetzen, AppDaemon lädt sie automatisch neu. Mit einem vorhandenen Clone:
```
cd /tmp/ha-power-flow-logger && git pull
cp apps/power_flow_logger/power_flow_logger.py /app_configs/<id>/apps/power_flow_logger/
```
oder den `curl`-Befehl aus b) erneut ausführen. Neue Konfigurationsoptionen stehen in `apps.yaml.example`. `/tmp` wird beim Neustart geleert, dann den Clone neu anlegen.

### Hinweise zur Konfiguration
- Wechselrichter fallen nachts oder bei Funkproblemen aus (Sensor `unavailable`). Mit `optional: true` zählt ein fehlender Wert dann als 0 W, sonst bleibt `verbrauch_w` leer.
- Die Altersspalte (`*_age_s`) beruht auf `last_updated`. Bei konstanten Werten (z. B. 0 W) steigt sie weiter an, weil HA den Zeitstempel dann nicht ändert. Sie taugt daher vor allem für sich ändernde Messwerte.

## Geplante Erweiterungen
- Viertelstunden-Mittel des Bezugs (an der Uhr ausgerichtet) und laufendes Monatsmaximum.
- SOC und Leistung der Speichertürme als Spalten.
- WR-Limit mitloggen und einen definierten Limit-Sprung testen, um die Totzeit zu messen.
- Entitäten-Auswahl per HA-Label statt YAML.

## Sicherheit und Datenschutz
- Die App ist rein lesend.
- Keine Logdaten (CSV) und keine Zugangsdaten ins Repo (siehe `.gitignore`).
