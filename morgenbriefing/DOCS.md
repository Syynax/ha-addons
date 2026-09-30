# Morgenbriefing

Zeigt die tägliche Zeitungs-Seite (HTML) in der Seitenleiste von Home Assistant.
Die Seite wird nicht hier erzeugt: Eine tägliche Aufgabe legt sie in ein GitHub-Repo,
das Add-on holt sie von dort ab.

## Einrichtung

1. **Repo zum Store hinzufügen:** Einstellungen → Add-ons → Add-on-Store → ⋮ → Repositories →
   `https://github.com/Syynax/ha-addons` eintragen.
2. **Token anlegen** (nur nötig, wenn das Daten-Repo privat ist): GitHub → Settings →
   Developer settings → Personal access tokens → Fine-grained tokens. Repository access:
   nur das Daten-Repo. Permissions: *Contents → Read-only*.
3. **Add-on installieren und Optionen setzen:**
   - `github_repo`: z. B. `Syynax/morgenbriefing-daten`
   - `github_branch`: `main`
   - `github_token`: der Token aus Schritt 2
   - `poll_minutes`: 15
4. Starten. „Morgenbriefing" erscheint in der Seitenleiste.

## Aufbau des Daten-Repos

```
latest.html            aktuelle Ausgabe (vollständiges HTML-Dokument)
summary.txt            Zusammenfassung in drei Sätzen (Klartext)
archive/JJJJ-MM-TT.html  ältere Ausgaben
```

Das Datum der Ausgabe liest das Add-on aus dem `<title>` (`Morgenbriefing TT.MM.JJJJ`).

## In Home Assistant

- **Sensor** `sensor.morgenbriefing`: Zustand = Datum der Ausgabe, Attribut `summary` = Zusammenfassung.
  Der Sensor wird beim Start des Add-ons neu gesetzt (er ist nicht dauerhaft gespeichert).
- **Ereignis** `morgenbriefing_neue_ausgabe`: wird ausgelöst, sobald eine neue Ausgabe abgeholt wurde
  (Daten: `edition`, `summary`).

Beispiel: Mitteilung aufs Handy bei neuer Ausgabe (Entität des Mobilgeräts anpassen):

```yaml
automation:
  - alias: Morgenbriefing ist da
    trigger:
      - platform: event
        event_type: morgenbriefing_neue_ausgabe
    action:
      - service: notify.mobile_app_dein_handy
        data:
          title: "Morgenbriefing"
          message: "{{ trigger.event.data.summary }}"
```

## Sicherheit

- Die Seite wird mit Content-Security-Policy ausgeliefert: **keine Skripte**, Sandbox ohne Zugriff
  auf Home Assistant. Bilder und Schriften werden nur über https geladen.
- Das Add-on ist nur über die Home-Assistant-Oberfläche (Ingress) erreichbar, nicht direkt im Netz.
- Der Token braucht nur Lesezugriff auf das Daten-Repo.

## Fehlersuche

- Seite leer oder Hinweis „noch keine Ausgabe": Repo-Name, Branch, Token und `latest.html` prüfen.
  Unter `…/status` (im Add-on) steht der letzte Fehler, „Jetzt abrufen" holt sofort neu.
- Ohne Internet zeigt das Add-on die zuletzt abgeholte Ausgabe.
