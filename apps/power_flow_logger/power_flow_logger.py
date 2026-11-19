"""AppDaemon-App: Belastungslog (nur lesen, schreibt nichts in HA).

Schreibt alle `interval` Sekunden eine CSV-Zeile pro Tag mit Rohwerten, Alter der
Werte (s seit last_updated, zur Latenzabschaetzung), der Netzleistung je Quelle
(Bezug +, Einspeisung -), dem berechneten Hausverbrauch und der Differenz der
Netzquellen zur primaeren Quelle.

Netzquellen (`grids`, beliebig viele, z. B. Hausanschluss-Messung und Netzbetreiber-Zaehler):
  name:
    entity: sensor.x            # EIN vorzeichenbehafteter Sensor (optional invert: true)
  name:
    in: sensor.a                # ODER zwei vorzeichenlose Sensoren (je >= 0)
    out: sensor.b

Speicherplatz (alle optional, siehe README):
  compress: true            # abgeschlossene Tage als .csv.gz packen (Standard: true)
  retention_days: 30        # Dateien aelter als N Tage loeschen (Standard: 30, 0 = nie)
  duration_days: 14         # nach N Tagen Aufzeichnung selbst stoppen (Standard: unbegrenzt)

Erzeuger (`inverters`) und sonstige Werte (`others`): entweder nur die Entity oder
  name:
    entity: sensor.x
    optional: true                  # fehlt/unavailable -> zaehlt als 0 W
    enabled: input_boolean.x        # Schalter; steht er auf "off", zaehlt die Quelle als 0 W
"""
import csv
import gzip
import os
import re
import shutil
from datetime import date, datetime, timedelta, timezone

import appdaemon.plugins.hass.hassapi as hass


def compute_grid(signed, grid_in, grid_out, invert=False):
    """Netzleistung in W (Bezug +, Einspeisung -). None, wenn Werte fehlen."""
    if signed is not None:
        return -signed if invert else signed
    if grid_in is None or grid_out is None:
        return None
    return grid_in - grid_out


def parse_grids(grids):
    """Prueft die Konfiguration und liefert {name: {"entity"|("in","out"), "invert"}}."""
    if not grids:
        raise ValueError("`grids` fehlt: mindestens eine Netzquelle angeben")
    out = {}
    for name, cfg in grids.items():
        cfg = dict(cfg or {})
        signed = cfg.get("entity")
        has_pair = cfg.get("in") and cfg.get("out")
        if bool(signed) == bool(has_pair):
            raise ValueError("Netzquelle '%s': entweder `entity` ODER `in` und `out` angeben" % name)
        out[name] = {"entity": signed, "in": cfg.get("in"), "out": cfg.get("out"),
                     "invert": bool(cfg.get("invert", False))}
    return out


def parse_sources(sources):
    """{name: entity | {entity, optional, enabled}} -> {name: {entity, optional, enabled}}."""
    out = {}
    for name, cfg in dict(sources or {}).items():
        if isinstance(cfg, str):
            cfg = {"entity": cfg}
        cfg = dict(cfg or {})
        if not cfg.get("entity"):
            raise ValueError("Quelle '%s': `entity` fehlt" % name)
        out[name] = {"entity": cfg["entity"], "enabled": cfg.get("enabled"),
                     "optional": bool(cfg.get("optional", False) or cfg.get("enabled"))}
    return out


def resolve_source(raw, optional, enabled_state):
    """Wert einer Quelle in W. Schalter 'off' -> 0; fehlender Wert -> 0 nur wenn optional."""
    if enabled_state is not None and str(enabled_state).lower() == "off":
        return 0.0
    if raw is None and optional:
        return 0.0
    return raw

LOG_RE = re.compile(r"^lastlog_(\d{4})-(\d{2})-(\d{2})\.csv(\.gz)?$")


def maintain(log_dir, today, compress=True, retention_days=30):
    """Packt abgeschlossene Tage (aelter als heute) und loescht alte Dateien.

    Gibt eine Liste der Aktionen zurueck: ("compress"|"delete", Dateiname).
    Fasst nur Dateien mit dem Muster lastlog_JJJJ-MM-TT.csv[.gz] an.
    """
    actions = []
    for fname in sorted(os.listdir(log_dir)):
        m = LOG_RE.match(fname)
        if not m:
            continue
        day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        path = os.path.join(log_dir, fname)
        gz = bool(m.group(4))
        if retention_days and day < today - timedelta(days=retention_days):
            os.remove(path)
            actions.append(("delete", fname))
        elif compress and not gz and day < today:
            tmp = path + ".gz.tmp"
            with open(path, "rb") as src, gzip.open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(tmp, path + ".gz")
            os.remove(path)
            actions.append(("compress", fname))
    return actions


class PowerFlowLogger(hass.Hass):
    def initialize(self):
        self.interval = int(self.args.get("interval", 1))
        self.log_dir = self.args.get("log_dir", "/config/appdaemon/lastlog")
        self.grids = parse_grids(self.args.get("grids"))
        self.primary = self.args.get("primary_grid", next(iter(self.grids)))
        if self.primary not in self.grids:
            raise ValueError("primary_grid '%s' nicht in `grids`" % self.primary)
        self.inverters = parse_sources(self.args.get("inverters"))  # WR-Ist, W
        self.others = parse_sources(self.args.get("others"))        # WP, Klima, Limit, ...
        self.compress = bool(self.args.get("compress", True))
        self.retention_days = int(self.args.get("retention_days", 30))
        duration = self.args.get("duration_days")
        self.duration_days = int(duration) if duration else None
        os.makedirs(self.log_dir, exist_ok=True)

        self.start_file = os.path.join(self.log_dir, ".lastlog_start")
        if self.duration_days and self._expired():
            self.log("Aufzeichnung beendet: duration_days=%d abgelaufen (Datei %s loeschen "
                     "oder duration_days aendern, um neu zu starten)"
                     % (self.duration_days, self.start_file), level="WARNING")
            return

        # Spaltenliste der Rohwerte: (Spaltenname, Entity)
        self.cols = []
        for name, g in self.grids.items():
            if g["entity"]:
                self.cols.append((name, g["entity"]))
            else:
                self.cols += [(name + "_in", g["in"]), (name + "_out", g["out"])]
        self.cols += [(n, s["entity"]) for n, s in self.inverters.items()]
        self.cols += [(n, s["entity"]) for n, s in self.others.items()]
        self.others_diff = [n for n in self.grids if n != self.primary]

        self.timer = None
        self.timer = self.run_every(self.snapshot, "now", self.interval)
        self.run_daily(self.cleanup, "00:05:00")
        self.run_in(self.cleanup, 10)
        self.log("Belastungslog gestartet (%s s, %d Sensoren, primaer: %s, packen: %s, "
                 "Aufbewahrung: %s, Dauer: %s)"
                 % (self.interval, len(self.cols), self.primary,
                    "ja" if self.compress else "nein",
                    "%d Tage" % self.retention_days if self.retention_days else "unbegrenzt",
                    "%d Tage" % self.duration_days if self.duration_days else "unbegrenzt"))

    def _expired(self):
        """Merkt sich den Startzeitpunkt in log_dir; True, wenn duration_days ueberschritten."""
        now = datetime.now(timezone.utc)
        try:
            with open(self.start_file) as f:
                start = datetime.fromisoformat(f.read().strip())
        except (OSError, ValueError):
            start = now
            with open(self.start_file, "w") as f:
                f.write(start.isoformat())
        return now - start >= timedelta(days=self.duration_days)

    def cleanup(self, kwargs):
        try:
            for action, fname in maintain(self.log_dir, datetime.now().date(),
                                          self.compress, self.retention_days):
                self.log("Log-Pflege: %s %s" % ("geloescht" if action == "delete" else "gepackt", fname))
        except OSError as exc:
            self.log("Log-Pflege fehlgeschlagen: %s" % exc, level="WARNING")

    @staticmethod
    def _num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _age(self, entity, now):
        ts = self.get_state(entity, attribute="last_updated")
        try:
            return round((now - datetime.fromisoformat(ts)).total_seconds(), 1)
        except (TypeError, ValueError):
            return None

    def _source_value(self, src, raw):
        enabled_state = self.get_state(src["enabled"]) if src["enabled"] else None
        return resolve_source(raw, src["optional"], enabled_state)

    def snapshot(self, kwargs):
        now = datetime.now(timezone.utc)
        if self.duration_days and self._expired():
            self.log("Aufzeichnung beendet: duration_days=%d abgelaufen" % self.duration_days,
                     level="WARNING")
            if self.timer:
                self.cancel_timer(self.timer)
            return
        raw = {n: self._num(self.get_state(e)) for n, e in self.cols}
        ages = {n: self._age(e, now) for n, e in self.cols}
        for name, src in list(self.inverters.items()) + list(self.others.items()):
            raw[name] = self._source_value(src, raw[name])

        net = {}
        for name, g in self.grids.items():
            if g["entity"]:
                net[name] = compute_grid(raw[name], None, None, g["invert"])
            else:
                net[name] = compute_grid(None, raw[name + "_in"], raw[name + "_out"])

        wr = [raw[n] for n in self.inverters]
        grid = net[self.primary]
        load = None
        if grid is not None and all(v is not None for v in wr):
            load = round(grid + sum(wr), 1)  # Verbrauch = Netz (Bezug +) + WR-Erzeugung
        diffs = [None if net[n] is None or grid is None else round(grid - net[n], 1)
                 for n in self.others_diff]
        nets = [None if net[n] is None else round(net[n], 1) for n in self.grids]

        header = (["ts"] + [n for n, _ in self.cols] + ["%s_age_s" % n for n, _ in self.cols]
                  + ["netz_%s_w" % n for n in self.grids] + ["verbrauch_w"]
                  + ["diff_%s_minus_%s_w" % (self.primary, n) for n in self.others_diff])
        row = ([now.astimezone().isoformat(timespec="seconds")]
               + [raw[n] for n, _ in self.cols] + [ages[n] for n, _ in self.cols]
               + nets + [load] + diffs)

        path = os.path.join(self.log_dir, "lastlog_%s.csv" % now.astimezone().strftime("%Y-%m-%d"))
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(header)
            w.writerow(row)
