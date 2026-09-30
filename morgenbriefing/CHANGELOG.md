# Änderungen

## 1.1.3
- Neu: Icon und Logo für das Add-on (Zeitungsseite, `icon.png` und `logo.png`).

## 1.1.2
- Repo-Eintrag wird bereinigt (auch `https://github.com/Owner/Repo` oder `.git` am Ende ist erlaubt), Anführungszeichen um den Token werden entfernt.
- Fehlermeldung bei 404 nennt jetzt, ob ein Token eingetragen ist und welches Repo und welcher Branch verwendet wurden.

## 1.1.1
- „Jetzt abrufen“ zeigt jetzt das Ergebnis an (neue Ausgabe, keine neuere Ausgabe oder der konkrete Fehler, z. B. Token ungültig) statt nur weiterzuleiten.

## 1.1.0
- Fehler behoben: Links in der Seitenleiste (Archiv, Jetzt abrufen) lieferten Fehler 401, weil die CSP-Sandbox die Ingress-Cookies abschnitt. Skripte bleiben weiterhin per CSP verboten.
- Neu: direkter Zugriff im Heimnetz ohne Home Assistant über `http://HA-IP:8099` (Option `lan_access`, nur private Adressen).
- Manueller Abruf hat jetzt 30 Sekunden Sperrzeit.

## 1.0.0
- Erste Version: Abruf aus GitHub, Anzeige per Ingress, Archiv, Sensor und Ereignis in Home Assistant.
