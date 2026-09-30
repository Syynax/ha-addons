# Änderungen

## 1.1.0
- Fehler behoben: Links in der Seitenleiste (Archiv, Jetzt abrufen) lieferten Fehler 401, weil die CSP-Sandbox die Ingress-Cookies abschnitt. Skripte bleiben weiterhin per CSP verboten.
- Neu: direkter Zugriff im Heimnetz ohne Home Assistant über `http://HA-IP:8099` (Option `lan_access`, nur private Adressen).
- Manueller Abruf hat jetzt 30 Sekunden Sperrzeit.

## 1.0.0
- Erste Version: Abruf aus GitHub, Anzeige per Ingress, Archiv, Sensor und Ereignis in Home Assistant.
