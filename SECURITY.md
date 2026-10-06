# Sicherheitshinweise

Dieses Projekt ist ein experimenteller Prototyp. Es gibt derzeit kein separates privates Meldepostfach und keinen zugesagten Security-Support-Zeitraum.

Für eine mögliche Schwachstelle zunächst ein Issue mit einer **allgemeinen Beschreibung ohne Geheimnisse, privaten Dokumenttext oder ausnutzbare Details** eröffnen und um einen privaten Meldeweg bitten. API-Schlüssel, Datenbanken und unbereinigte Protokolle niemals öffentlich einstellen.

Der lokale Dienst ist für `127.0.0.1` vorgesehen. Der Client-Header ist keine geheime Authentifizierung. Nicht per Portfreigabe, Reverse Proxy oder LAN-Bindung öffentlich verfügbar machen.

Eigene Hugging-Face-Modelle müssen mit dem unterstützten lokalen Encoder kompatibel sein. Das Projekt aktiviert keinen fremden Modellcode über `trust_remote_code`. Für Dokumente und Cloud-Anbieter gelten die Angaben in [DATA.md](docs/DATA.md).
