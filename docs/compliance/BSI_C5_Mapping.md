# BSI IT-Grundschutz / C5 Kontrollzuordnung

*(BSI IT-Grundschutz / C5 Control Mapping)*

> **Entwurf — vor Verwendung durch einen Rechtsanwalt/Datenschutzbeauftragten
> zu prüfen.** Insbesondere die Einordnung als Auftragsverarbeiter/
> Verantwortlicher (siehe `TOM.md`) bedarf rechtlicher Bestätigung.
>
> (Draft — must be reviewed by a lawyer/data protection officer before
> real use. In particular, the controller/processor classification
> requires legal confirmation.)

## Geltungsbereich dieser Zuordnung

Diese Zuordnung deckt ausschließlich die C5/IT-Grundschutz-Domänen ab, die
von den **Kontrollen dieser Software selbst** berührt werden. Domänen, die
in die Verantwortung des Hosting-Anbieters oder des Kunden (physische
Sicherheit des Rechenzentrums, Personalsicherheit, organisatorische
Richtlinien des Kunden) fallen, sind hier bewusst **nicht** aufgeführt —
eine Software-Appliance kann diese nicht selbst erfüllen.

## IDM — Identitäts- und Berechtigungsmanagement (Identity and Access Management)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Rollenbasierte Zugriffskontrolle | `rag/crosscutting/security/` — granulare Berechtigungsprüfung pro Endpunkt |
| Mehr-Faktor-Authentifizierung | `rag/crosscutting/security/mfa.py` |
| Sitzungs-Widerruf | Entzogene Berechtigungen wirken sich auf die nächste Anfrage aus |

## KRY — Kryptografie und Schlüsselmanagement (Cryptography and Key Management)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Verschlüsselung ruhender Daten | Envelope-Encryption-Keystore (`rag/crosscutting/security/keystore.py`) |
| Verschlüsselung während der Übertragung | TLS-Terminierung via nginx-Reverse-Proxy (`nginx/nginx.conf`), automatische Zertifikatserzeugung bei Installation (`rag/bootstrap/tls_cert.py`) |
| Schlüsselvernichtung als Löschmechanismus | Crypto-Shred pro Konversation, siehe `Loeschkonzept.md` |

## LOG — Protokollierung und Überwachung (Logging and Monitoring)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Manipulationssicheres Audit-Log | Hash-verkettetes Log mit Erkennung nachträglicher Änderungen (`rag/crosscutting/security/audit.py`) |
| Systemmetriken und Alarmierung | Prometheus/Grafana-Stack mit Alarmregeln (z. B. geringer Speicherplatz), strukturiertes JSON-Logging |
| Fehlerverfolgung | Selbst-gehostetes Fehler-Tracking (GlitchTip) |

## BEI — Betriebskontinuität und Notfallmanagement (Backup and Recovery)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Verschlüsseltes Backup | Keystore-gesicherte Archive (`rag/backup/`) |
| Getestetes Restore-Verfahren | Tatsächlich end-to-end getestet, nicht nur angenommen (Integrationstests) |
| Automatischer Neustart bei Container-Ausfall | Docker-Compose-Neustartrichtlinien, Healthchecks |

## PSS / SWD — Patch- und Schwachstellenmanagement (Patch and Vulnerability Management)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Container-Image-Schwachstellenscans | Trivy-Scan bei jedem Merge in der CI-Pipeline, hartes Ausschlusskriterium für CRITICAL-Schwachstellen (`.github/workflows/ci.yml`) |
| Reproduzierbare, versionsgesperrte Abhängigkeiten | `uv.lock` |
| Signierte Update-Bundles | Ed25519-signierte Offline-Update-Bundles, Signaturprüfung vor Installation |

## Außerhalb des Geltungsbereichs dieser Software (Out of Scope)

Diese Domänen sind für ein produktives BSI-C5/Grundschutz-Audit relevant,
liegen jedoch außerhalb dessen, was eine Software-Appliance selbst
kontrollieren kann:

- **Physische Sicherheit** des Rechenzentrums/Serverraums — Verantwortung
  des Kunden bzw. des Hosting-Anbieters.
- **Personalsicherheit** (Background-Checks, Vertraulichkeitsvereinbarungen
  für Mitarbeitende des Kunden) — Verantwortung des Kunden.
- **Organisatorische Richtlinien** (interne Prozesse, Schulungen) —
  Verantwortung des Kunden als Betreiber der Appliance.
